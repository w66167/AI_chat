# -*- coding: utf-8 -*-
"""校验评测问题集的内部一致性。

重点检查：gold 是否存在、must_include 是否真的出现在 gold 原文里、
题型与期望行为是否匹配、题目是否重复、文档覆盖是否过于集中。
没有通过校验的题目，评出来的分数不可信。
"""
import json
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')

VALID_EXPECT = {'answer', 'answer_with_caveat', 'clarify',
                'refuse_noanswer', 'refuse_boundary', 'refuse_conflict'}
NO_GOLD_TYPES = {'clarify', 'noanswer', 'boundary'}
TARGET_TOTAL = 150


def main():
    payload = json.load(open(os.path.join(DATA, 'eval_questions.json'), encoding='utf-8'))
    items = payload['items']
    chunks = {}
    with open(os.path.join(DATA, 'handbook_chunks.jsonl'), encoding='utf-8') as f:
        for line in f:
            c = json.loads(line)
            chunks[c['id']] = c

    errors, warns = [], []
    seen_q, seen_id = {}, set()

    for it in items:
        eid = it['id']
        if eid in seen_id:
            errors.append('%s 编号重复' % eid)
        seen_id.add(eid)
        q = it['question'].strip()
        if not q:
            errors.append('%s 问题为空' % eid)
        if q in seen_q:
            errors.append('%s 与 %s 问题重复：%s' % (eid, seen_q[q], q))
        seen_q[q] = eid
        if it['expect'] not in VALID_EXPECT:
            errors.append('%s 期望行为 %s 不合法' % (eid, it['expect']))
        if not it['note']:
            warns.append('%s 缺少标注说明' % eid)

        for g in it['gold']:
            if g not in chunks:
                errors.append('%s 的命中目标 %s 不存在' % (eid, g))
        if it['type'] in NO_GOLD_TYPES and it['gold']:
            errors.append('%s 属于 %s，不应标注命中目标' % (eid, it['type']))
        if it['type'] in ('standard', 'synonym', 'multiturn', 'conflict') and not it['gold']:
            errors.append('%s 属于 %s，必须标注命中目标' % (eid, it['type']))
        if it['type'] == 'multiturn' and 'ctx' not in it:
            errors.append('%s 是多轮追问，缺少上一轮上下文' % eid)
        if it['type'] == 'conflict' and it['expect'] != 'answer_with_caveat':
            errors.append('%s 是冲突题，期望行为应为 answer_with_caveat' % eid)

        if it['gold']:
            body = ''.join(chunks[g]['text'] for g in it['gold'] if g in chunks)
            for kw in it['must_include']:
                if kw not in body:
                    errors.append('%s 的必含词「%s」不在命中块原文中' % (eid, kw))
            if not it['must_include']:
                warns.append('%s 未设置必含词，无法判定答案是否正确' % eid)
            # 问题与命中块应确有话题关联：用二元组重合做粗筛（命中块标错时此处会报警）
            stop = {'学生', '规定', '学校', '可以', '如何', '应当', '什么', '怎么', '哪些', '需要'}
            qs = {q[i:i + 2] for i in range(len(q) - 1)} - stop
            bs = {body[i:i + 2] for i in range(len(body) - 1)} - stop
            if it['type'] in ('standard', 'synonym') and not (qs & bs):
                warns.append('%s 问题与命中块无共同二元组，请人工确认未标错' % eid)

        if it['type'] == 'multiturn':
            prev = it['ctx'].get('prev_gold')
            if prev and prev not in chunks:
                errors.append('%s 的上一轮命中块 %s 不存在' % (eid, prev))

    counts = Counter(it['type'] for it in items)
    print('总条数 %d（目标 %d）' % (len(items), TARGET_TOTAL))
    if len(items) != TARGET_TOTAL:
        errors.append('条数不等于 %d' % TARGET_TOTAL)
    print('题型分布：' + '，'.join('%s %d' % (k, v) for k, v in counts.items()))

    gold_docs = Counter()
    for it in items:
        for d in it.get('gold_docs', []):
            gold_docs[d] += 1
    print('命中目标覆盖手册文件 %d 篇' % len(gold_docs))
    used = {g for it in items for g in it['gold']}
    print('使用的不同切块 %d 个（语料共 %d 个）' % (len(used), len(chunks)))
    print('  引用最多的 5 篇：')
    for doc, n in gold_docs.most_common(5):
        print('    %2d 条  %s' % (n, doc[:38]))

    # 难度分布，避免全是简单题
    diff = Counter(it['difficulty'] for it in items)
    print('难度分布：' + '，'.join('L%d %d' % (k, diff[k]) for k in sorted(diff)))

    for w in warns:
        print('[警告]', w)
    for x in errors:
        print('[错误]', x)
    print('结果：%s（错误 %d，警告 %d）' % ('通过' if not errors else '未通过', len(errors), len(warns)))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
