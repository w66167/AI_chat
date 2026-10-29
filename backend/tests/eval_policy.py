# -*- coding: utf-8 -*-
"""用 150 条评测集给「策略层」打分。

测的不是模型，而是 answer.py 的判断：该答的答了没、该拒的拒了没、该问的问了没。
产出 predictions.json，交给 scripts/score_eval.py 用同一套规则评分。

    & "..\knowledge_base\.venv\Scripts\python.exe" tests\eval_policy.py
    & "..\knowledge_base\.venv\Scripts\python.exe" ..\knowledge_base\scripts\score_eval.py \
        --predictions ..\knowledge_base\data\predictions_policy.json
"""
import json
import os
import sys
import time

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app import answer, deps            # noqa: E402
from app.schemas import AskRequest, HistoryTurn  # noqa: E402


def main():
    cfg = deps.get_config()
    print('加载检索器（约 12 秒）……')
    retriever = deps.get_retriever()

    eval_path = os.path.join(cfg.kb.root, 'data', 'eval_questions.json')
    items = json.load(open(eval_path, encoding='utf-8'))['items']

    preds, rows = {}, []
    t0 = time.time()
    for it in items:
        # 多轮题把上一轮问题作为 history 传入，还原线上会话
        history = []
        ctx = it.get('ctx') or {}
        if it['type'] == 'multiturn' and ctx.get('prev_question'):
            history = [HistoryTurn(question=ctx['prev_question'])]

        req = AskRequest(question=it['question'], history=history)
        t1 = time.perf_counter()
        resp = answer.respond(req, cfg=cfg, retriever=retriever)
        cost = (time.perf_counter() - t1) * 1000

        top3 = [c['chunk_id'] for c in resp['citations']]
        preds[it['id']] = {'top3': top3, 'answer': resp['answer'],
                           'behavior': resp['behavior'], 'confidence': resp['confidence']}
        rows.append((it['id'], it['type'], it['question'], resp['behavior'],
                     round(resp['confidence'], 2), len(top3), int(cost)))

    out = os.path.join(cfg.kb.root, 'data', 'predictions_policy.json')
    json.dump(preds, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # 行为分布：能直接看出阈值是不是偏严或偏松
    dist = {}
    for _, typ, _, behavior, conf, _, _ in rows:
        dist.setdefault(typ, {}).setdefault(behavior, 0)
        dist[typ][behavior] += 1

    print('\n总耗时 %.1f 秒，平均 %.0f ms/题' % (time.time() - t0,
                                          sum(r[6] for r in rows) / len(rows)))
    print('\n行为分布（题型 → 系统实际给出的 behavior）')
    for typ, cnt in dist.items():
        total = sum(cnt.values())
        detail = '，'.join('%s %d' % (b, n) for b, n in sorted(cnt.items(), key=lambda x: -x[1]))
        print('  %-9s %3d 题 → %s' % (typ, total, detail))

    print('\npredictions 已写入 %s' % out)
    print('下一步：')
    print(r'  & "%s" "%s" --predictions "%s"' % (
        os.path.join(cfg.kb.root, '.venv', 'Scripts', 'python.exe'),
        os.path.join(cfg.kb.root, 'scripts', 'score_eval.py'), out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
