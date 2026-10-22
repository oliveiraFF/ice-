"""脚本方法（切片版）。

有商品事实 → 引用并追溯（status=ready）；无事实 → 出草案（status=draft）。
后续接 LLM 时只替换 generate_script 的实现，接口不变。
"""

BEAT_ORDER = ["hook", "scene", "proof", "method", "limitation", "cta"]


def generate_script(topic, brief, facts=None):
    product = _str(brief.get("product")) or "你的产品"
    audience = _str(brief.get("audience")) or "目标用户"
    angle = _str(topic.get("angle")) or "结构复刻"

    fact_items = (facts or {}).get("facts") or []
    status = "ready" if fact_items else "draft"
    missing = [] if fact_items else ["未提供商品事实（facts）"]

    if fact_items:
        proof_text = "、".join(f["content"] for f in fact_items)
        fact_ids = [f["id"] for f in fact_items]
    else:
        proof_text = "（待补真实卖点，不编造）"
        fact_ids = []

    beats = [
        {"beat": "hook", "text": "别再瞎试了，{0}这件事，记住一个点就够了。".format(angle)},
        {"beat": "scene", "text": "我是{0}，{1}这个场景我踩过坑。".format(audience, product)},
        {"beat": "proof", "text": proof_text, "fact_ids": fact_ids},
        {"beat": "method", "text": "三步：① 先看结果 ② 再讲结构 ③ 最后给方法。"},
        {"beat": "limitation", "text": "注意：效果因人而异，不承诺夸张结果；缺数据用「待补」标注。"},
        {"beat": "cta", "text": "想要同款思路，评论区扣「1」。"},
    ]
    full_text = "".join(b["text"] for b in beats)
    return {
        "topic": _str(topic.get("topic")),
        "angle": angle,
        "status": status,
        "missing": missing,
        "beats": beats,
        "full_text": full_text,
        "estimated_seconds": max(15, len(full_text) // 4),
    }


def _str(value):
    return value.strip() if isinstance(value, str) else ""
