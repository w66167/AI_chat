# -*- coding: utf-8 -*-
"""延迟分解：把一次问答拆成「转向量 / 检索 / 重排」分别计时，给出 P50/P95/P99。

为什么不能只看平均值：P95 才是用户体感。若 P95 是 3 秒，平均 1 秒也救不了每 20 个
用户里那 1 个等 3 秒的人。

用法：
    python scripts/latency_bench.py                 # 150 题全跑
    python scripts/latency_bench.py --limit 60      # 快速试
"""
import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kb import config, metrics  # noqa: E402
from kb.hybrid import HybridRetriever, PipelinedRetriever  # noqa: E402
from kb.lexical import BM25Retriever  # noqa: E402
from kb.corpus import load_chunks  # noqa: E402


def pct(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return s[idx]


def summarize(name, ms):
    return {
        'stage': name,
        'n': len(ms),
        'mean': round(statistics.mean(ms), 1),
        'p50': round(pct(ms, 50), 1),
        'p95': round(pct(ms, 95), 1),
        'p99': round(pct(ms, 99), 1),
        'max': round(max(ms), 1),
        'qps': round(1000.0 / statistics.mean(ms), 2) if ms else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 题')
    ap.add_argument('--warmup', type=int, default=5)
    args = ap.parse_args()

    cfg = config.load()
    items = metrics.load_eval(metrics.resolve(cfg['paths']['eval_path'], cfg.root))['items']
    if args.limit:
        items = items[:args.limit]
    from embed_bench import build_query
    queries = [build_query(it) for it in items]

    path = cfg['corpus']['chunks_path']
    if not os.path.isabs(path):
        path = os.path.join(cfg.root, path)
    chunks = load_chunks(path)
    by_id = {c.id: c for c in chunks}

    from kb.embedder import build_embedder
    from kb.index import Index
    from kb.rerank import build_reranker
    from kb.retriever import VectorRetriever, expected_fingerprint, index_path

    alias, spec = cfg.model()
    print('加载模型……')
    index = Index.load(index_path(cfg, alias), expected_fingerprint(cfg, alias, spec))
    embedder = build_embedder(cfg, alias)
    reranker = build_reranker(cfg)
    bm25 = BM25Retriever(by_id, [(c.id, c.text) for c in chunks])

    t_embed, t_bm25, t_rerank20, t_rerank10, t_e2e20, t_e2e10 = [], [], [], [], [], []

    def sync():
        import torch
        if torch.cuda.is_available():
            torch.cuda.synchronize()

    for q in queries[:args.warmup]:
        embedder.encode([q], is_query=True)
        bm25.search(q, k=20)
        reranker.rerank(q, [(c.id, c.text) for c in chunks[:20]], top_k=3)

    print('计时中（%d 题）……' % len(queries))
    fused_meta = []
    for qi, q in enumerate(queries):
        sync(); t0 = time.perf_counter()
        qv = embedder.encode([q], is_query=True)[0]
        sync(); t_embed.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        bm25.search(q, k=20)
        t_bm25.append((time.perf_counter() - t0) * 1000)

        # 用「真实融合候选」计时，而不是语料前 N 条——候选长度直接决定交叉编码器耗时
        vec = VectorRetriever(index, embedder, by_id)
        plain = HybridRetriever(vec, bm25, None, candidates=20,
                                rrf_k=cfg['retrieval'].get('rrf_k', 60), chunks_by_id=by_id)
        cand = [(cid, by_id[cid].text) for cid, _ in plain.search(q, k=20) if cid in by_id]
        for bucket, n in ((t_rerank20, 20), (t_rerank10, 10)):
            part = cand[:n]
            sync(); t0 = time.perf_counter()
            reranker.rerank(q, part, top_k=3)
            sync(); bucket.append((time.perf_counter() - t0) * 1000)
        fused_meta.append((len(cand), sum(len(t) for _, t in cand) // max(len(cand), 1)))

        # 端到端：完整混合检索链路
        for n, bucket in ((20, t_e2e20), (10, t_e2e10)):
            hy = HybridRetriever(VectorRetriever(index, embedder, by_id), bm25, reranker,
                                 candidates=n, rrf_k=cfg['retrieval'].get('rrf_k', 60),
                                 chunks_by_id=by_id)
            sync(); t0 = time.perf_counter()
            hy.search(q, k=3)
            sync(); bucket.append((time.perf_counter() - t0) * 1000)

    stages = [summarize('① 查询转向量', t_embed),
              summarize('② BM25 检索', t_bm25),
              summarize('③ 重排（真实候选 20）', t_rerank20),
              summarize('③ 重排（真实候选 10）', t_rerank10),
              summarize('▶ 端到端 混合+重排(20)', t_e2e20),
              summarize('▶ 端到端 混合+重排(10)', t_e2e10)]

    print('\n| 环节 | 平均 | P50 | P95 | P99 | 最大 | 单进程 QPS |')
    print('| --- | --- | --- | --- | --- | --- | --- |')
    for s in stages:
        print('| %s | %.1f ms | %.1f ms | %.1f ms | %.1f ms | %.1f ms | %.2f |'
              % (s['stage'], s['mean'], s['p50'], s['p95'], s['p99'], s['max'], s['qps']))

    # 持续负载下的降频：把端到端序列切成前后两半对比
    if len(t_e2e20) >= 20:
        half = len(t_e2e20) // 2
        first = statistics.mean(t_e2e20[:half])
        last = statistics.mean(t_e2e20[half:])
        print('\n持续负载对比（端到端 20 候选）：前 %d 题平均 %.0f ms → 后 %d 题平均 %.0f ms（+%.0f%%）'
              % (half, first, len(t_e2e20) - half, last, 100.0 * (last - first) / first))
    avg_len = sum(m[1] for m in fused_meta) / max(len(fused_meta), 1)
    print('候选平均长度：%.0f 字（长度直接影响交叉编码器耗时）' % avg_len)

    out = os.path.join(cfg.root, 'data', 'latency_results.json')
    json.dump({'n': len(queries), 'stages': stages}, open(out, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\n结果已写入 %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
