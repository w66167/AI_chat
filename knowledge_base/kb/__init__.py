# -*- coding: utf-8 -*-
"""检索层对外包。

典型用法：

    from kb import config, retriever
    cfg = config.load()
    r = retriever.load_retriever(cfg)          # 按 config.json 的 active 模型
    for chunk_id, score in r.search("宿舍几点熄灯"):
        print(chunk_id, score, r.ref(chunk_id)['source'])

config / corpus / lexical / metrics 只用标准库，随包导入；
embedder / index / retriever 依赖 numpy（和 torch），按需加载——
这样没有显卡、没装模型环境的服务器也能跑关键词检索（见 backend/app/deps.py 的保底路径）。
"""
import importlib

from . import config, corpus, lexical, metrics

_LAZY = ('embedder', 'index', 'retriever', 'hybrid', 'rerank')
__all__ = ['config', 'corpus', 'embedder', 'index', 'lexical', 'metrics', 'retriever']


def __getattr__(name):
    if name in _LAZY:
        return importlib.import_module('.' + name, __name__)
    raise AttributeError('module %r has no attribute %r' % (__name__, name))
