# -*- coding: utf-8 -*-
"""混合检索：向量召回与关键词召回用 RRF 融合。

为什么用 RRF（Reciprocal Rank Fusion）而不是加权分数：
两条路径的分数量纲完全不同（余弦 0~1，BM25 无上界），归一化后加权需要调参；
RRF 只看名次，天然免疫量纲差异，且不需要调参就能稳定优于单路。

score = Σ 1/(k + rank)，k 一般取 60。
"""


def rrf(results_list, k=60, top_k=3):
    """results_list: [[(chunk_id, score), ...], ...]，每个子列表已按分数降序。"""
    fused = {}
    for results in results_list:
        for rank, (chunk_id, _score) in enumerate(results, 1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
    ranked = sorted(fused.items(), key=lambda x: -x[1])
    return ranked[:top_k]


class PipelinedRetriever:
    """单路检索 + 重排：先用 base 取 candidates，再交给重排模型。"""

    def __init__(self, base, reranker, candidates=20, chunks_by_id=None, name=None):
        self.base = base
        self.reranker = reranker
        self.candidates = candidates
        self.chunks = chunks_by_id
        self.name = name or (base.name + '+rerank')

    def search(self, query, k=3):
        pool = max(self.candidates, k)
        cand = self.base.search(query, k=pool)
        pairs = [(cid, self.chunks[cid].text) for cid, _ in cand if cid in self.chunks]
        return self.reranker.rerank(query, pairs, top_k=k)


def build_retrievers(cfg, which=('bm25', 'vector', 'hybrid', 'hybrid+rerank'), log=print):
    """按需装配检索器。只加载实际用到的模型，避免为了跑 BM25 也去加载 1.3 GB 权重。"""
    import os

    from .corpus import load_chunks
    from .embedder import build_embedder
    from .index import Index
    from .lexical import BM25Retriever
    from .rerank import build_reranker
    from .retriever import VectorRetriever, expected_fingerprint, index_path

    which = list(which)
    # 依赖展开：hybrid 必须有 vector+bm25；带重排的必须有 reranker。
    # 这里自动补齐，调用方不用记依赖关系（之前 server 直接要 hybrid+rerank 就踩了 KeyError）。
    need_vector = any(w.startswith(('vector', 'hybrid')) for w in which)
    need_bm25 = any(w == 'bm25' or w.startswith('hybrid') for w in which)

    path = cfg['corpus']['chunks_path']
    if not os.path.isabs(path):
        path = os.path.join(cfg.root, path)
    chunks = load_chunks(path)
    by_id = {c.id: c for c in chunks}

    out = {}
    if need_bm25:
        out['bm25'] = BM25Retriever(by_id, [(c.id, c.text) for c in chunks])

    if need_vector:
        alias, spec = cfg.model()
        index = Index.load(index_path(cfg, alias), expected_fingerprint(cfg, alias, spec))
        embedder = build_embedder(cfg, alias, log=log)
        out['vector'] = VectorRetriever(index, embedder, by_id, name='vector')

    need_rerank = any(w.endswith('+rerank') for w in which)
    reranker = build_reranker(cfg, log=log) if need_rerank else None
    cand = cfg['retrieval'].get('candidates', 20)

    if 'hybrid' in which:
        out['hybrid'] = HybridRetriever(out['vector'], out['bm25'], None,
                                        candidates=cand, rrf_k=cfg['retrieval'].get('rrf_k', 60),
                                        chunks_by_id=by_id)
    if 'vector+rerank' in which and reranker:
        out['vector+rerank'] = PipelinedRetriever(out['vector'], reranker, cand, by_id)
    if 'hybrid+rerank' in which and reranker:
        out['hybrid+rerank'] = HybridRetriever(out['vector'], out['bm25'], reranker,
                                               candidates=cand,
                                               rrf_k=cfg['retrieval'].get('rrf_k', 60),
                                               chunks_by_id=by_id)
    return {k: v for k, v in out.items() if k in which}


class HybridRetriever:
    """向量 + BM25 融合；可选在候选集上加一层重排。

    流程：两路各取 candidates 个 → RRF 融合 → （可选）重排 → 取 top_k。
    重排只作用于融合后的候选，成本可控，也不会让某一路的长尾噪声进入最终结果。
    """

    def __init__(self, vector, lexical, reranker=None, candidates=20, rrf_k=60,
                 name=None, chunks_by_id=None):
        self.vector = vector
        self.lexical = lexical
        self.reranker = reranker
        self.candidates = candidates
        self.rrf_k = rrf_k
        self.name = name or ('hybrid' + ('+rerank' if reranker else ''))
        self.chunks = chunks_by_id

    def search(self, query, k=3):
        pool = max(self.candidates, k)
        vec = self.vector.search(query, k=pool)
        lex = self.lexical.search(query, k=pool)
        fused = rrf([vec, lex], self.rrf_k, pool)
        if self.reranker is None:
            return fused[:k]
        pairs = [(cid, self.chunks[cid].text) for cid, _ in fused if cid in self.chunks]
        reranked = self.reranker.rerank(query, pairs, top_k=k)
        return reranked
