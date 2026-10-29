# -*- coding: utf-8 -*-
"""检索对比评测：同一套 150 题，量出每条检索路径能拿多少分。

用法：
    python scripts/embed_bench.py                       # 跑 bm25 / vector / hybrid / hybrid+rerank
    python scripts/embed_bench.py --pipelines hybrid
    python scripts/embed_bench.py --rebuild             # 重建索引后再测
    python scripts/embed_bench.py --show-failures 6

设计要点：所有路径共用 kb.metrics.topk_hit，分数可比。
多轮题会把上一轮问题一起送进检索（build_query），还原线上真实输入。
结果写入 data/bench_results.json。
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kb import config, metrics  # noqa: E402
from kb.hybrid import build_retrievers  # noqa: E402

ALL = ('bm25', 'vector', 'hybrid', 'vector+rerank', 'hybrid+rerank')


def build_query(item):
    """多轮题要把上一轮问题一起送进检索，否则「周末也这样吗」单看毫无信息。"""
    ctx = item.get('ctx') or {}
    if item['type'] == 'multiturn' and ctx.get('prev_question'):
        return ctx['prev_question'] + ' ' + item['question']
    return item['question']


def eval_retriever(r, items, k=3):
    preds, failures = {}, []
    for it in items:
        got = [cid for cid, _ in r.search(build_query(it), k=k)]
        preds[it['id']] = {'top3': got}
        if it['gold'] and not (set(got) & set(it['gold'])):
            failures.append((it['id'], it['type'], it['question'], it['gold'], got))
    rows = metrics.topk_hit(preds, items, k)
    return preds, metrics.summarize_topk(rows), failures


def fmt(n_ok, n):
    return '%d/%d (%.1f%%)' % (n_ok, n, 100.0 * n_ok / n if n else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pipelines', help='逗号分隔：%s' % ','.join(ALL))
    ap.add_argument('--k', type=int, default=None)
    ap.add_argument('--show-failures', type=int, default=0)
    ap.add_argument('--candidates', type=int, default=0, help='覆盖 config 的候选数')
    args = ap.parse_args()

    cfg = config.load()
    if args.candidates:
        cfg['retrieval']['candidates'] = args.candidates
    k = args.k or cfg['retrieval']['top_k']
    items = metrics.load_eval(metrics.resolve(cfg['paths']['eval_path'], cfg.root))['items']
    which = [w.strip() for w in args.pipelines.split(',')] if args.pipelines else list(ALL[:3])
    if 'hybrid+rerank' in which or 'vector+rerank' in which:
        which = list(dict.fromkeys(which + ['vector', 'bm25']))

    t0 = time.time()
    retrievers = build_retrievers(cfg, which)
    print('装配耗时 %.1f 秒\n' % (time.time() - t0))

    results = {}
    for name in which:
        r = retrievers.get(name)
        if r is None:
            continue
        t0 = time.time()
        _, summary, failures = eval_retriever(r, items, k)
        cost = time.time() - t0
        results[name] = {'overall': summary['overall'], 'by_type': summary['by_type'],
                         'cost_s': round(cost, 1)}
        print('%-16s %s   (%.1fs)' % (name, fmt(*summary['overall']), cost))
        if args.show_failures:
            for fid, ftype, q, gold, got in failures[:args.show_failures]:
                print('   %s [%s] %s' % (fid, ftype, q[:24]))
                print('     期望 %s 实得 %s' % (gold, got))

    print('\n| 检索路径 | Top-%d 命中 | 标准问 | 同义问法 | 多轮追问 | 冲突题 |' % k)
    print('| --- | --- | --- | --- | --- | --- |')
    for name, r in results.items():
        bt = r['by_type']

        def cell(t):
            ok, n = bt.get(t, (0, 0))
            return '%d/%d' % (ok, n)
        print('| %s | **%s** | %s | %s | %s | %s |'
              % (name, fmt(*r['overall']), cell('standard'), cell('synonym'),
                 cell('multiturn'), cell('conflict')))

    out = os.path.join(cfg.root, 'data', 'bench_results.json')
    json.dump({'k': k, 'corpus_version': cfg['corpus']['version'],
               'max_chars': cfg['corpus']['max_chars'],
               'candidates': cfg['retrieval'].get('candidates'),
               'results': results},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n结果已写入 %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())


