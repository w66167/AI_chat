# -*- coding: utf-8 -*-
"""检索层：对上层只暴露 search(text, k)，返回引用单元而不是内部 id。

向量检索与关键词检索实现同一个 Retriever 接口，这样评测时两条路径
走的是同一个打分函数，分数才可比。
"""
import os
from typing import Protocol

from .index import Index, fingerprint
from .corpus import load_chunks, build_units


class Retriever(Protocol):
    name: str

    def search(self, query, k=3):
        """返回 [(parent_chunk_id, score)]，按分数降序，已按引用单元去重。"""
        ...


class VectorRetriever:
    def __init__(self, index, embedder, chunks_by_id, name=None):
        self.index = index
        self.embedder = embedder
        self.chunks = chunks_by_id
        self.name = name or getattr(embedder, 'name', 'vector')

    def search(self, query, k=3):
        """先把检索单元按 parent 去重，再取前 k 个引用单元。"""
        qv = self.embedder.encode([query], is_query=True)[0]
        # 多取一些单元，避免同一长条的子块挤满结果
        raw = self.index.search(qv, k=max(k * 4, 12))
        best, order = {}, []
        for unit_id, score in raw:
            parent = unit_id.split('#')[0]
            if parent not in best:
                best[parent] = score
                order.append(parent)
        return [(p, best[p]) for p in order[:k]]

    def ref(self, chunk_id):
        c = self.chunks.get(chunk_id)
        return c.as_ref() if c else None


def index_path(cfg, alias):
    return os.path.join(cfg.path('index_dir'), '%s.npz' % alias)


def expected_fingerprint(cfg, alias, spec):
    return fingerprint(spec['model_id'], spec.get('dim'),
                       cfg['corpus']['version'], cfg['corpus']['max_chars'],
                       cfg['embedder'].get('normalize', True),
                       cfg['corpus'].get('exclude_articles') or ())


def load_retriever(cfg, alias=None):
    """按配置加载「语料 + 索引 + 嵌入模型」，返回可直接查询的检索器。"""
    from .embedder import build_embedder

    alias, spec = cfg.model(alias)
    chunks, units = load_corpus(cfg)
    chunks_by_id = {c.id: c for c in chunks}
    index = Index.load(index_path(cfg, alias), expected_fingerprint(cfg, alias, spec))
    if index.size != len(units):
        raise RuntimeError('索引单元数 %d 与语料单元数 %d 不一致，请重建索引'
                           % (index.size, len(units)))
    embedder = build_embedder(cfg, alias)
    return VectorRetriever(index, embedder, chunks_by_id, name=alias)


def load_corpus(cfg):
    path = cfg['corpus']['chunks_path']
    if not os.path.isabs(path):
        path = os.path.join(cfg.root, path)
    chunks = load_chunks(path)
    units = build_units(chunks, cfg['corpus']['max_chars'], cfg['corpus']['min_chars'])
    return chunks, units


def build_index(cfg, alias=None, embedder=None):
    """离线建索引：语料 → 检索单元 → 向量 → 指纹。幂等，可重复执行。"""
    from .embedder import build_embedder as make_embedder

    alias, spec = cfg.model(alias)
    chunks, units = load_corpus(cfg)
    embedder = embedder or make_embedder(cfg, alias)
    vectors = embedder.encode([u.text for u in units], is_query=False)
    if vectors.shape[1] != spec.get('dim', vectors.shape[1]):
        raise RuntimeError('向量维度 %d 与配置 dim=%s 不一致' % (vectors.shape[1], spec.get('dim')))
    index = Index(unit_ids=[u.id for u in units],
                  parent_ids=[u.parent_id for u in units],
                  vectors=vectors,
                  fingerprint=expected_fingerprint(cfg, alias, spec),
                  meta={'model': spec['model_id'], 'alias': alias, 'dim': int(vectors.shape[1]),
                        'chunks': len(chunks), 'units': len(units),
                        'corpus_version': cfg['corpus']['version'],
                        'max_chars': cfg['corpus']['max_chars']})
    path = index_path(cfg, alias)
    index.save(path)
    return index, path, chunks
