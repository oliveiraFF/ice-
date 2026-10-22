"""Illustrative fixtures, not collected platform content."""
import time


def sample_posts():
    now = time.time()
    rows = [
        ('清洁好物', 'xhs', '厨房清洁原来可以这么省力', '小禾的生活实验', 9, 2860, 1720, 136, 6800, 'clean', ['效果对比', '厨房清洁'], '把重油污清洁的前后效果放在一起，观察它如何展示产品用途。'),
        ('清洁好物', 'dy', '用了三年的锅底，终于洗回来了', '阿简居家日记', 18, 5200, 894, 320, 9200, 'pan', ['效果对比', '产品实测'], '旧锅翻新的产品演示。可以留意开场是否直接呈现问题，以及效果证明的顺序。'),
        ('清洁好物', 'xhs', '浴室边角清洁，这几个地方别漏掉', '住进理想生活', 31, 1840, 2600, 98, None, 'bath', ['场景清单', '浴室清洁'], '围绕细小清洁场景组织内容，适合观察一个商品如何对应多个使用位置。'),
        ('清洁好物', 'dy', '别再用错清洁工具了！', '认真生活研究所', 6, 960, 185, 76, 4300, 'brush', ['避坑指南', '产品实测'], '从常见的使用错误切入，再展示工具选择。只是演示选题，不代表真实效果或销量。'),
        ('清洁好物', 'xhs', '周末半小时，把家里的小角落清一遍', '一只收纳鹿', 62, 3100, 1460, 210, None, 'cloth', ['场景清单', '日常分享'], '用日常打扫串联多个工具，适合记录场景顺序与商品出现的时机。'),
        ('清洁好物', 'dy', '两种清洁刷放一起，差别在哪里？', '好物观察员', 46, 2450, 460, 188, 12500, 'compare', ['效果对比', '工具对比'], '同一场景下比较两种工具，为后期分析保留对比维度。'),
        ('桌面收纳', 'xhs', '一平米书桌，也能留出自己的空间', '慢慢整理', 14, 1480, 2100, 83, None, 'storage', ['空间改造', '桌面收纳'], '演示收纳主题内容，展示关键词之间的数据隔离。'),
        ('桌面收纳', 'dy', '桌上的线，终于不用再找了', '桌面计划', 28, 2360, 820, 156, 7800, 'storage', ['痛点解决', '桌面收纳'], '演示理线工具的场景化选题。'),
        ('通勤好物', 'xhs', '每天出门，这个小包就够了', '路上见', 20, 920, 610, 48, None, 'bag', ['日常分享', '通勤场景'], '演示通勤主题，不是真实平台笔记。'),
    ]
    result = {}
    for index, row in enumerate(rows):
        keyword, platform, title, author, age, likes, saves, comments, followers, artwork, tags, description = row
        post = dict(external_id='demo-{}'.format(index), platform=platform, title=title, author=author,
                    published_at=now-age*3600, likes=likes, saves=saves, comments=comments, followers=followers,
                    cover=None, duration=None, url=None, tags=tags, artwork=artwork, description=description)
        result.setdefault(keyword, []).append(post)
    return result
