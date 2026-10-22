"""商品事实：加载与校验。

facts.json 结构：
{
  "product": "长柄清洁刷",
  "facts": [
    {"id": "F1", "content": "刷头可拆卸", "source": "商品详情页"}
  ]
}
"""
import json
from pathlib import Path


class FactsError(Exception):
    pass


def load_facts(path):
    path = Path(path)
    if not path.exists():
        raise FactsError("facts 文件不存在：%s" % path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise FactsError("facts 文件不是合法 JSON：%s" % exc)
    except OSError as exc:
        raise FactsError("facts 文件无法读取：%s" % exc)
    return validate_facts(data)


def validate_facts(data):
    if not isinstance(data, dict):
        raise FactsError("facts 顶层必须是对象")
    product = data.get("product")
    if not isinstance(product, str) or not product.strip():
        raise FactsError("缺少 product（商品名）")
    facts = data.get("facts")
    if not isinstance(facts, list) or not facts:
        raise FactsError("facts 必须是非空数组")

    seen = set()
    cleaned = []
    for offset, fact in enumerate(facts, 1):
        if not isinstance(fact, dict):
            raise FactsError("第 %d 条事实不是对象" % offset)
        ident = fact.get("id")
        content = fact.get("content")
        source = fact.get("source")
        if not isinstance(ident, str) or not ident.strip():
            raise FactsError("第 %d 条事实缺少 id" % offset)
        ident = ident.strip()
        if not isinstance(content, str) or not content.strip():
            raise FactsError("事实 %s 缺少 content" % ident)
        if not isinstance(source, str) or not source.strip():
            raise FactsError("事实 %s 缺少 source" % ident)
        if ident in seen:
            raise FactsError("事实 id 重复：%s" % ident)
        seen.add(ident)
        cleaned.append({"id": ident, "content": content.strip(), "source": source.strip()})

    return {"product": product.strip(), "facts": cleaned}
