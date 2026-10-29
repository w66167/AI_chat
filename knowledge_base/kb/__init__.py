# -*- coding: utf-8 -*-
"""检索层对外包。

典型用法：

    from kb import config, retriever
    cfg = config.load()
    r = retriever.load_retriever(cfg)          # 按 config.json 的 active 模型
    for chunk_id, score in r.search("宿舍几点熄灯"):
        print(chunk_id, score, r.ref(chunk_id)['source'])
"""
from . import config, corpus, embedder, index, lexical, metrics, retriever

__all__ = ['config', 'corpus', 'embedder', 'index', 'lexical', 'metrics', 'retriever']
