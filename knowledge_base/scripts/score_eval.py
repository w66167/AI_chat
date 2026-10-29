# -*- coding: utf-8 -*-
"""对外部系统输出打分（系统级评测）。

检索实现不在这里：BM25 在 kb/lexical.py，向量检索在 kb/retriever.py，
本文件只负责「读题目 → 拿预测 → 按规则判分 → 汇总」。
基线与真实系统因此走同一个 judge()，分数才可比。

用法：
    python scripts/score_eval.py --baseline
    python scripts/score_eval.py --predictions predictions.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kb import config, metrics  # noqa: E402
from kb.lexical import BM25Retriever  # noqa: E402

THRESHOLDS = {'top3': 0.90, 'noanswer': 0.95, 'clarify': 0.90}


def baseline_predictions(cfg, items, threshold=12.0):
    """关键词基线的预测。它不生成答案，只能给出 Top-3 与是否拒答。"""
    from kb.corpus import load_chunks
    path = cfg['corpus']['chunks_path']
    if not os.path.isabs(path):
        path = os.path.join(cfg.root, path)
    chunks = load_chunks(path)
    r = BM25Retriever({c.id: c for c in chunks}, [(c.id, c.text) for c in chunks])
    preds = {}
    for it in items:
        top = r.search(it['question'], k=3)
        best = top[0][1] if top else 0.0
        preds[it['id']] = {'top3': [cid for cid, _ in top], 'answer': '',
                           'behavior': 'refuse_noanswer' if best < threshold else 'answer',
                           'score': round(best, 2)}
    return preds


def evaluate(items, preds, retrieval_only=False):
    counts, fails = {}, []
    hits = []
    for it in items:
        pred = preds.get(it['id']) or {}
        if it['gold']:
            hits.append(bool(set((pred.get('top3') or [])[:3]) & set(it['gold'])))
        if retrieval_only and it['expect'] in ('answer', 'answer_with_caveat'):
            got = pred.get('top3') or []
            ok = bool(set(got[:3]) & set(it['gold']))
            reason = '' if ok else '未命中前3'
            if ok and pred.get('behavior') == 'refuse_noanswer':
                ok, reason = False, '命中但被拒答'
        else:
            ok, reason = metrics.judge(it, pred)
        ok_n, total = counts.get(it['type'], (0, 0))
        counts[it['type']] = (ok_n + int(ok), total + 1)
        if not ok:
            fails.append((it['id'], it['type'], it['question'], reason))
    return counts, fails, hits


def report(counts, fails, hits):
    print('\n%-10s %5s %5s %7s' % ('题型', '通过', '总数', '通过率'))
    for t, (ok, n) in counts.items():
        print('%-10s %5d %5d %6.1f%%' % (t, ok, n, 100.0 * ok / n if n else 0))

    if hits:
        print('\n纯检索 Top-3 命中率：%.1f%%  (%d/%d)  ← 不含拒答与内容判定'
              % (100.0 * sum(hits) / len(hits), sum(hits), len(hits)))

    def rate(types):
        ok = sum(counts[t][0] for t in types if t in counts)
        n = sum(counts[t][1] for t in types if t in counts)
        return ok, n

    ok, n = rate(['standard', 'synonym', 'multiturn', 'conflict'])
    print('检索类端到端通过率：%.1f%%  (%d/%d)  目标 ≥ %.0f%%'
          % (100.0 * ok / n, ok, n, THRESHOLDS['top3'] * 100))
    ok2, n2 = rate(['noanswer'])
    print('无答案正确拒答率：%.1f%%  (%d/%d)  目标 ≥ %.0f%%'
          % (100.0 * ok2 / n2, ok2, n2, THRESHOLDS['noanswer'] * 100))
    ok3, n3 = rate(['clarify'])
    print('澄清题正确率：%.1f%%  (%d/%d)  目标 ≥ %.0f%%'
          % (100.0 * ok3 / n3, ok3, n3, THRESHOLDS['clarify'] * 100))
    ok4, n4 = rate(['boundary'])
    print('边界题合规率：%.1f%%  (%d/%d)' % (100.0 * ok4 / n4, ok4, n4))

    if fails:
        print('\n未通过明细（前 25 条）：')
        for fid, ftype, q, reason in fails[:25]:
            print('  %s [%s] %s  -> %s' % (fid, ftype, q[:26], reason))
        if len(fails) > 25:
            print('  …… 另有 %d 条' % (len(fails) - 25))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', action='store_true', help='关键词基线自测（不生成答案）')
    ap.add_argument('--predictions', help='系统输出 JSON')
    ap.add_argument('--threshold', type=float, default=12.0,
                    help='基线拒答阈值（在本题库上校准，仅作对照）')
    args = ap.parse_args()

    cfg = config.load()
    payload = metrics.load_eval(metrics.resolve(cfg['paths']['eval_path'], cfg.root))
    items = payload['items']

    if args.predictions:
        preds = json.load(open(args.predictions, encoding='utf-8'))
        print('评测模式：真实系统输出（%d 条预测 / %d 条题目）' % (len(preds), len(items)))
        retrieval_only = False
    elif args.baseline:
        preds = baseline_predictions(cfg, items, args.threshold)
        print('评测模式：关键词基线（BM25 二元组，只有检索能力，无生成与澄清）')
        retrieval_only = True
    else:
        print('请指定 --baseline 或 --predictions。predictions 格式：')
        print(json.dumps({'ev-001': {'top3': ['hb-123'], 'answer': '……', 'behavior': 'answer'}},
                         ensure_ascii=False, indent=1))
        return 2

    counts, fails, hits = evaluate(items, preds, retrieval_only=retrieval_only)
    report(counts, fails, hits)
    return 0


if __name__ == '__main__':
    sys.exit(main())
