"""用 LLM 生成脚本（单 provider）。输出交给 workflow 做事实/结构校验。"""
import json

from tools.llm_call import call_llm, LLMError

_SYSTEM = ("你是电商短视频编剧。只基于给定商品事实写口播稿，"
           "面向正在看商品的消费者，禁止编造。")


def _reference_lines(references):
    lines = []
    for item in references or []:
        report = item.get('report') or {}
        scope = item.get('scope') or {}
        limit = scope.get('limitation') or ('%s 张采样画面' % scope.get('frames') if scope.get('frames') else '范围未知')
        lines.append('- 参考%s《%s》（模型：%s；来源：%s；范围：%s）' % (
            item.get('id'), item.get('title') or '', item.get('model') or '未知',
            item.get('source_name') or item.get('source_type') or '未知', limit))
        if report.get('summary'):
            lines.append('  摘要：' + str(report['summary'])[:300])
        for row in (report.get('observations') or [])[:3]:
            lines.append('  观察：%s；建议：%s' % (
                str(row.get('evidence') or '')[:120], str(row.get('advice') or '')[:120]))
        if scope.get('limitation'):
            lines.append('  分析限制：' + str(scope['limitation'])[:300])
    return '\n'.join(lines) if lines else '（未选择参考）'


def _pain_lines(pains):
    lines = []
    for item in pains or []:
        lines.append('- %s（来源：%s，证据：%s，频次：%s）' % (
            item.get('pain') or '', item.get('source') or '未知',
            item.get('evidence_role') or '未标注', item.get('frequency')))
        if item.get('evidence'):
            lines.append('  原摘录：' + str(item['evidence'])[:200])
    return '\n'.join(lines) if lines else '（未选择痛点）'


def _suggestion_lines(suggestions):
    lines = []
    for item in suggestions or []:
        suggestion = item.get('suggestion') or {}
        lines.append('- %s（依据：%s；条件：%s；待验证：%s）' % (
            suggestion.get('text') or '', suggestion.get('basis') or '未提供',
            suggestion.get('conditions') or '未提供', suggestion.get('pending') or '未提供'))
    return '\n'.join(lines) if lines else '（未选择建议）'


def build_script_prompt(topic, brief, facts, references=None, pains=None, suggestions=None):
    fact_lines = "\n".join(
        "- %s：%s（来源：%s）" % (f["id"], f["content"], f["source"]) for f in facts["facts"])
    user = (
        "商品：%s\n受众：%s\n具体主题：%s\n受众问题：%s\n可用事实：\n%s\n\n"
        "选中参考（仅用于开场/结构/节奏，不是本商品事实；不得把参考里的品牌、功效、价格写成本商品内容）：\n%s\n\n"
        "选中痛点（仅作表达关注点；不是已验证需求或本商品事实；不得写成普遍比例或效果）：\n%s\n\n"
        "复盘建议（执行参考，不是商品事实；不是因果结论；不得写成已验证效果）：\n%s\n\n"
        "目标：写一条面向消费者的商品口播，20–25 秒，正常语速约 80–110 字。\n"
        "要求：\n"
        "1. 口播是给消费者听的商品介绍，不是包装设计分析；不要出现“结构复刻”“三层信息”"
        "“卖点拆解”等内部方法词。\n"
        "2. proof 段必须引用 fact_ids，且只能用上面列出的事实编号；不得编造。\n"
        "3. 未提供背标、配料表、营养值、实测或续集时，不承诺展示这些内容；可以说“还没看到/待补”。\n"
        "4. method 段写消费者下一步的查看动作（如看背标），不写内部方法。\n"
        "5. 参考只影响结构与节奏，痛点只影响关注点；两者都不能成为商品功效、成分、价格或实测证明。\n"
        "6. 只输出 JSON，结构：\n"
        '{"beats":[{"beat":"hook","text":"..."},{"beat":"scene","text":"..."},'
        '{"beat":"proof","text":"...","fact_ids":["F1"]},{"beat":"method","text":"..."},'
        '{"beat":"limitation","text":"..."},{"beat":"cta","text":"..."}]}\n'
        "只输出 JSON，不要额外说明。"
    ) % (brief.get("product", ""), brief.get("audience", ""),
         topic.get("topic", ""), topic.get("angle", ""), fact_lines,
         _reference_lines(references), _pain_lines(pains), _suggestion_lines(suggestions))
    return _SYSTEM, user


def generate_script_llm(topic, brief, facts, llm_config=None, references=None, pains=None, suggestions=None):
    system, user = build_script_prompt(topic, brief, facts, references=references, pains=pains,
                                       suggestions=suggestions)
    result = call_llm([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], config=llm_config)
    data = _parse_json(result["text"])
    _validate(data)
    beats = data["beats"]

    text = "".join(str(b.get("text") or "") for b in beats)
    return {
        "topic": _str(topic.get("topic")),
        "angle": _str(topic.get("angle")) or "结构复刻",
        "status": "draft",
        "missing": [],
        "beats": beats,
        "full_text": text,
        "estimated_seconds": max(15, len(text) // 4),
        "source": "llm",
        "model": result.get("model"),
        "usage": result.get("usage"),
        "duration_ms": result.get("duration_ms"),
    }


def _validate(data):
    if not isinstance(data, dict):
        raise LLMError("LLM 输出顶层不是对象")
    beats = data.get("beats")
    if not isinstance(beats, list) or not beats:
        raise LLMError("LLM 输出 beats 必须是非空数组")
    for offset, beat in enumerate(beats, 1):
        if not isinstance(beat, dict):
            raise LLMError("第 %d 个 beat 不是对象" % offset)
        if not isinstance(beat.get("beat"), str) or not beat["beat"].strip():
            raise LLMError("第 %d 个 beat 缺少 beat 名称" % offset)
        if not isinstance(beat.get("text"), str) or not beat["text"].strip():
            raise LLMError("第 %d 个 beat 的 text 无效" % offset)
        ids = beat.get("fact_ids")
        if ids is not None and (not isinstance(ids, list) or any(not isinstance(x, str) for x in ids)):
            raise LLMError("第 %d 个 beat 的 fact_ids 必须是字符串数组" % offset)


def _parse_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except ValueError:
        raise LLMError("LLM 输出不是合法 JSON")


def _str(value):
    return value.strip() if isinstance(value, str) else ""
