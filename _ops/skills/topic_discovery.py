"""选题方法（切片版）。

先规则 stub：从作品样本生成最多 3 条选题候选（角度 + 理由 + 来源）。
后续接 LLM 时只替换 generate_topic_candidates 的实现，接口不变。
"""


def generate_topic_candidates(keyword, posts, count=3):
    if not posts:
        return []
    ranked = sorted(posts, key=lambda p: p.get("plays") or 0, reverse=True)
    candidates = []
    for post in ranked[:count]:
        angle = _guess_angle(post)
        candidates.append({
            "topic": "「%s」%s" % (keyword, angle),
            "angle": angle,
            "reason": "样本播放 %s、点赞 %s；可借其结构做同主题不同角度" % (
                _num(post.get("plays")), _num(post.get("likes"))),
            "source_ids": [post.get("id")],
        })
    return candidates


def _guess_angle(post):
    text = (post.get("title", "") + " " + " ".join(post.get("tags", [])))
    if any(k in text for k in ("误区", "做错", "避坑")):
        return "误区纠正"
    if any(k in text for k in ("对比", "前后", "实测")):
        return "对比实测"
    if any(k in text for k in ("清单", "合集")):
        return "清单合集"
    return "结构复刻"


def _num(value):
    if value is None:
        return "未知"
    return "{:,}".format(value)
