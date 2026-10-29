# -*- coding: utf-8 -*-
"""评测指标：只关心「检索/回答结果 vs 评测集标注」，不关心用的是什么模型。

检索类指标与行为类指标分开计算：
  检索 Top-k 命中率 —— 只看排名里有没有 gold 块
  端到端通过率     —— 还要看行为对不对、必含词有没有、禁用表述有没有

两者差值反映「检索没错但答错了」的比例，是排查问题时最有用的一个数。
"""
import json
import os

PROTECT = ('以学校文件为准', '以现行', '现行文件', '可能已', '版本', '时效')


def load_eval(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def resolve(path, root):
    return path if os.path.isabs(path) else os.path.join(root, path)


def topk_hit(predictions, items, k=3):
    """只算检索：gold 是否出现在前 k 名。predictions: {id: {"top3": [...]}}"""
    rows = []
    for it in items:
        if not it['gold']:
            continue
        got = (predictions.get(it['id']) or {}).get('top3') or []
        hit = bool(set(got[:k]) & set(it['gold']))
        rows.append((it['id'], it['type'], hit, it['gold'], got[:k]))
    return rows


def summarize_topk(rows):
    by_type = {}
    for _, typ, hit, _, _ in rows:
        ok, n = by_type.get(typ, (0, 0))
        by_type[typ] = (ok + int(hit), n + 1)
    ok = sum(1 for r in rows if r[2])
    return {'overall': (ok, len(rows)), 'by_type': by_type}


def judge(item, pred):
    """单题判定：检索命中 + 行为正确 + 内容合规。返回 (通过, 原因)。"""
    expect = item['expect']
    got = pred.get('top3') or []
    behavior = pred.get('behavior') or ''
    answer = pred.get('answer') or ''
    hit = bool(set(got[:3]) & set(item['gold'])) if item['gold'] else None
    clean = not any(x in answer for x in item.get('must_not') or [])
    missing = [k for k in (item.get('must_include') or []) if k not in answer]

    if expect == 'answer':
        ok = behavior == 'answer' and hit and clean and not missing
        return ok, '' if ok else ('未命中前3' if not hit else (
            '含禁用表述' if not clean else '缺必含词 %s' % missing))
    if expect == 'answer_with_caveat':
        caveat = any(x in answer for x in PROTECT)
        ok = behavior == 'answer_with_caveat' and hit and clean and caveat
        return ok, '' if ok else ('未命中前3' if not hit else (
            '含禁用表述' if not clean else '未提示时效'))
    if expect == 'clarify':
        return behavior == 'clarify', '' if behavior == 'clarify' else '未澄清'
    if expect == 'refuse_noanswer':
        ok = behavior == 'refuse_noanswer' and clean
        return ok, '' if ok else ('编造内容' if not clean else '未拒答')
    if expect == 'refuse_boundary':
        ok = behavior == 'refuse_boundary' and clean
        return ok, '' if ok else ('出现承诺性表述' if not clean else '未按边界拒答')
    return False, '未知期望行为 %s' % expect
