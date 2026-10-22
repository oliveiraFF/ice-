"""T06：基于发布登记与指标快照的确定性复盘（不调用模型）；M03 支持引用咨询摘录。"""
KEY_LABELS = {'plays': '播放', 'likes': '点赞', 'comments': '评论',
              'favorites': '收藏', 'inquiries': '咨询'}


def _describe(metrics):
    parts = ['%s %s' % (KEY_LABELS[key], metrics[key])
             for key in KEY_LABELS if metrics.get(key) is not None]
    return '、'.join(parts) if parts else '无已知指标'


def build_review(record, snapshots, consultations=None):
    consultations = consultations or []
    known = [item for item in snapshots
             if any(value is not None for value in (item.get('metrics') or {}).values())]
    if not known and not consultations:
        return {'status': 'insufficient',
                'observations': ['暂无已知指标，也没有咨询摘录，不能复盘'],
                'suggestions': []}
    observations = []
    if known:
        latest = known[-1]
        observations.append('最新快照（采集 %s）：%s' % (latest['collected_at'], _describe(latest['metrics'])))
        if len(known) >= 2:
            previous = known[-2]
            if str(previous.get('definition') or '') != str(latest.get('definition') or ''):
                observations.append('最近两份快照口径不同（%s / %s），不能直接比较' % (
                    previous.get('definition') or '未标注', latest.get('definition') or '未标注'))
            else:
                for key, label in KEY_LABELS.items():
                    old = previous['metrics'].get(key)
                    new = latest['metrics'].get(key)
                    if old is not None and new is not None and old != new:
                        observations.append('%s从 %s 变为 %s' % (label, old, new))
    if consultations:
        observations.append('咨询摘录 %d 条（用户手动记录，非平台核验）：%s' % (
            len(consultations), '；'.join(str(item.get('text') or '')[:60] for item in consultations[:3])))
        observations.append('咨询摘录条数是独立样本数；指标中的咨询次数是用户录入的统计值，二者不能相加或互相替代')
    if consultations and not known:
        observations.append('没有自有指标：不能判断传播/转化效果，只能引用咨询原文')
    suggestions = []
    if known:
        metrics = known[-1]['metrics']
        plays, comments = metrics.get('plays'), metrics.get('comments')
        if plays is not None and comments is not None and plays > 0:
            suggestions.append({
                'text': '在结尾加一个明确提问，观察评论数是否变化',
                'basis': '最近快照评论 %s / 播放 %s（本作品口径，非行业标准）' % (comments, plays),
                'conditions': '同一作品、同一累计口径、后续快照',
                'pending': '需要下一份快照验证，不能据此声称提升',
            })
        suggestions.append({
            'text': '补充下一条指标快照，保持同口径再比较',
            'basis': '当前仅有 %d 份已知快照' % len(known),
            'conditions': '同一作品、同一口径',
            'pending': '样本不足，暂不判断因果',
        })
    if consultations:
        suggestions.append({
            'text': '围绕咨询“%s”准备一次回复演练，并在下一条内容中观察是否出现同类问题' % str(
                consultations[0].get('text') or '')[:30],
            'basis': '咨询摘录 %d 条（人工记录）' % len(consultations),
            'conditions': '用户手动记录；单条摘录不能称普遍需求',
            'pending': '需新数据验证，不能据此声称提升',
        })
    return {'status': 'ok', 'observations': observations, 'suggestions': suggestions}
