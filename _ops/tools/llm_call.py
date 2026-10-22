"""最小 LLM 调用封装（单 provider：OpenAI 兼容，默认 DeepSeek）。

- 仅在 LLM_AUTHORIZED=1 + LLM_ALLOW_PAID=1 + 配置 LLM_API_KEY 时真实调用。
- LLM_ALLOW_PAID 只是运行许可开关，不代表契约 forbid 已变更；真调前需 owner 批准最小规则变更。
- 不跟随任何 HTTP 重定向：Authorization 不会转发到 Location 目标。
- 地址在创建网络请求前校验：仅支持 HTTPS；HTTP 仅允许本机回环地址。
- 否则抛 LLMNotConfigured，调用方回退 stub。
- 超时 / 输出上限 / 不自动重试。
- 记录 model / usage / duration，不记录 key。
"""
import ipaddress
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

_ENDPOINT_ERROR = ('模型服务地址无效：仅支持 HTTPS；本机回环地址（localhost/127.0.0.1/[::1]）'
                   '可使用 HTTP；地址不能带账号、密码或无效端口')


class LLMError(Exception):
    pass


class LLMNotConfigured(LLMError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """拒绝所有 301/302/303/307/308，不把请求发给 Location 目标。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _is_loopback(host):
    host = (host or '').strip('[]').lower()
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_endpoint(base):
    """校验服务地址；只做字符串解析，不发起 DNS 或网络连接。"""
    if not isinstance(base, str) or not base.strip():
        raise LLMNotConfigured('本次请求缺少服务地址或模型')
    parsed = urlsplit(base.strip())
    try:
        port = parsed.port
    except ValueError:
        raise LLMNotConfigured(_ENDPOINT_ERROR) from None
    if parsed.scheme not in ('http', 'https') or not parsed.hostname \
            or parsed.username or parsed.password:
        raise LLMNotConfigured(_ENDPOINT_ERROR)
    if port is not None and not 0 < port < 65536:
        raise LLMNotConfigured(_ENDPOINT_ERROR)
    if parsed.scheme == 'http' and not _is_loopback(parsed.hostname):
        raise LLMNotConfigured(_ENDPOINT_ERROR)
    return base.strip().rstrip('/')


def _open(request, timeout):
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)


def is_configured():
    return (bool(os.getenv("LLM_API_KEY", "").strip())
            and os.getenv("LLM_AUTHORIZED", "") == "1"
            and os.getenv("LLM_ALLOW_PAID", "") == "1")


def call_llm(messages, max_tokens=800, timeout=60, config=None):
    if config is not None:
        if not config.get("api_key"):
            raise LLMNotConfigured("本次请求缺少模型密钥")
        if config.get("authorized") is not True:
            raise LLMNotConfigured("本次真实调用未确认授权")
        if config.get("allow_paid") is not True:
            raise LLMNotConfigured("未获得付费调用许可（LLM_ALLOW_PAID=1）")
        base = (config.get("base_url") or "").rstrip("/")
        model = config.get("model") or ""
        key = config.get("api_key") or ""
        if not base or not model:
            raise LLMNotConfigured("本次请求缺少服务地址或模型")
    else:
        if not is_configured():
            raise LLMNotConfigured("未配置或未授权 LLM（需 LLM_API_KEY + LLM_AUTHORIZED=1 + LLM_ALLOW_PAID=1）")
        base = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
        model = os.getenv("LLM_MODEL", "deepseek-chat")
        key = os.getenv("LLM_API_KEY", "").strip()
    base = validate_endpoint(base)
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(base + "/chat/completions", data, {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
    })

    started = time.time()
    try:
        with _open(request, timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LLMError("LLM 返回 HTTP %s" % exc.code)
    except (urllib.error.URLError, OSError) as exc:
        raise LLMError("LLM 连接失败或超时：%s" % exc)
    except ValueError:
        raise LLMError("LLM 响应不是合法 JSON")
    duration = int((time.time() - started) * 1000)

    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("LLM 响应结构无效")

    return {
        "text": text,
        "model": body.get("model", model),
        "usage": body.get("usage") or {},
        "duration_ms": duration,
    }
