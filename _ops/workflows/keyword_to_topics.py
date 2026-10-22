"""确定性流程：关键词 → 拉取 → 选题候选 → 校验 → 返回。

这是「关键词 → 选题」垂直切片的最小闭环。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.fetch_douyin import fetch_by_keyword, FetchError
from skills.topic_discovery import generate_topic_candidates


def run(keyword, limit=10):
    keyword = (keyword or "").strip()
    if not keyword:
        return _blocked("关键词为空")

    try:
        posts = fetch_by_keyword(keyword, limit)
    except FetchError as exc:
        return _blocked("拉取失败：" + str(exc))

    if not posts:
        return _blocked("没有匹配的作品样本")

    candidates = [c for c in generate_topic_candidates(keyword, posts) if _valid(c)]
    if not candidates:
        return _blocked("候选校验未通过")

    evidence = [{"source": "douyin", "ref": p.get("id")} for p in posts[:3]]
    return {
        "task": "topics",
        "status": "ok",
        "blocked_reason": None,
        "outputs": {"keyword": keyword, "candidates": candidates},
        "evidence": evidence,
        "next_actions": ["选 1 条候选，进入脚本环节"],
    }


def _valid(candidate):
    return (isinstance(candidate, dict)
            and isinstance(candidate.get("topic"), str) and bool(candidate["topic"])
            and isinstance(candidate.get("reason"), str) and bool(candidate["reason"])
            and isinstance(candidate.get("source_ids"), list) and bool(candidate["source_ids"]))


def _blocked(reason):
    return {
        "task": "topics",
        "status": "blocked",
        "blocked_reason": reason,
        "outputs": {},
        "evidence": [],
        "next_actions": ["换关键词或检查数据源"],
    }
