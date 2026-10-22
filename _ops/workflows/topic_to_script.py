"""确定性流程：选题 + 商品 brief（+ 事实）→ 脚本 → 校验 → 返回。

- 无事实 → 脚本为 draft（缺事实），不可发布。
- use_llm=True 时优先用真实 LLM；未配置/失败则回退 stub。
- LLM 输出仍经结构 + 事实引用校验，ready 由本流程判定。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills.script_writing import generate_script, BEAT_ORDER
from tools.facts import validate_facts, FactsError
from tools.llm_script import generate_script_llm
from tools.llm_call import LLMError, LLMNotConfigured


def run(topic, brief, facts=None, use_llm=False, llm_config=None, references=None, pains=None, suggestions=None):
    if not isinstance(topic, dict) or not topic.get("topic"):
        return _blocked("缺少选题")
    if not isinstance(brief, dict) or not brief.get("product"):
        return _blocked("缺少商品信息")

    if facts is not None:
        try:
            facts = validate_facts(facts)
        except FactsError as exc:
            return _blocked("事实无效：" + str(exc))
        if facts["product"] != brief["product"].strip():
            return _blocked("商品与事实不匹配：brief=%s facts=%s" % (brief["product"], facts["product"]))

    source, llm_error, script = "stub", None, None
    if use_llm and facts:
        try:
            script = generate_script_llm(topic, brief, facts, llm_config=llm_config,
                                         references=references, pains=pains, suggestions=suggestions)
            source = "llm"
        except LLMNotConfigured as exc:
            llm_error = str(exc)
        except LLMError as exc:
            return _llm_blocked(str(exc))
    if script is None:
        script = generate_script(topic, brief, facts)

    if not _valid(script):
        return _blocked("脚本结构校验未通过")

    problems = _fact_problems(script, facts)
    if problems:
        script["status"] = "draft"
        script["missing"] = problems
    else:
        script["status"] = "ready" if facts else "draft"

    draft = script.get("status") != "ready"
    return {
        "task": "script",
        "status": "ok",
        "blocked_reason": None,
        "outputs": {"script": script, "source": source, "llm_error": llm_error},
        "evidence": _evidence(script),
        "next_actions": ["补充事实后重新生成（当前为草案）" if draft else "按脚本拍摄，或交给 AI 视频生成"],
    }


def _fact_problems(script, facts):
    if not facts:
        return []
    known = {f["id"] for f in facts["facts"]}
    problems = []
    proof_ids = []
    for beat in script.get("beats") or []:
        if beat.get("beat") == "proof":
            proof_ids.extend(beat.get("fact_ids") or [])
        for ident in beat.get("fact_ids") or []:
            if ident not in known:
                problems.append("引用了不存在的事实 %s" % ident)
    if not proof_ids:
        problems.append("proof 段未引用任何事实")
    return problems


def _evidence(script):
    ids = set()
    for beat in script.get("beats") or []:
        for ident in beat.get("fact_ids") or []:
            ids.add(ident)
    return [{"source": "fact", "ref": ident} for ident in sorted(ids)]


def _valid(script):
    beats = script.get("beats") or []
    kinds = [b.get("beat") for b in beats]
    return (all(k in kinds for k in BEAT_ORDER)
            and all(b.get("text") for b in beats)
            and bool(script.get("full_text")))


def _blocked(reason):
    return {
        "task": "script",
        "status": "blocked",
        "blocked_reason": reason,
        "outputs": {},
        "evidence": [],
        "next_actions": ["补齐选题或商品信息"],
    }


def _llm_blocked(reason):
    return {
        "task": "script",
        "status": "blocked",
        "blocked_reason": "LLM 调用失败：" + reason,
        "outputs": {"source": "llm", "llm_error": reason},
        "evidence": [],
        "next_actions": ["检查 LLM 配置或稍后重试（不自动重试）"],
    }
