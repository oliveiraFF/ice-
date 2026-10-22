"""按关键词拉取抖音作品。

- 默认（无 SLICE_LIVE）：读本机样本 fixtures/sample_posts.json，切片可直接跑。
- 设 SLICE_LIVE=1 且有 TIKHUB_API_KEY：走真实接口（当前占位，未接线）。

失败抛 FetchError，不返回 None 假装成功。
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "sample_posts.json"


class FetchError(Exception):
    pass


def fetch_by_keyword(keyword, limit=10):
    keyword = (keyword or "").strip()
    if not keyword:
        raise FetchError("关键词为空")
    live = os.getenv("SLICE_LIVE", "") == "1"
    key = os.getenv("TIKHUB_API_KEY", "").strip()
    if live and key:
        return _fetch_real(keyword, limit)
    return _fetch_fixture(keyword, limit)


def _fetch_fixture(keyword, limit):
    if not FIXTURE.exists():
        raise FetchError("缺少本地样本 fixtures/sample_posts.json")
    posts = json.loads(FIXTURE.read_text(encoding="utf-8"))
    matched = []
    for post in posts:
        haystack = " ".join([post.get("title", "")] + list(post.get("tags", [])))
        if keyword in haystack:
            matched.append(post)
    return matched[:limit]


def _fetch_real(keyword, limit):
    # 真实接口未接线：明确报错，避免静默失败
    raise FetchError("真实接口尚未接线；清空 SLICE_LIVE 使用本地样本")
