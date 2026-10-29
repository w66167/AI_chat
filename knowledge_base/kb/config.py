# -*- coding: utf-8 -*-
"""检索层配置：所有可调参数的唯一入口。

优先级：显式参数 > config.json > 代码默认值。
模型名、路径、阈值都不写死在业务代码里（NFR-08 可替换性）。
"""
import json
import os
from copy import deepcopy

DEFAULT = {
    'corpus': {
        'chunks_path': 'data/handbook_chunks.jsonl',
        'version': 'hb-2017-v1',
        'max_chars': 500,      # 检索单元长度上限（bge 512 token 限制的保守值）
        'min_chars': 40,       # 拆到这么短就不再拆
    },
    'embedder': {
        'active': 'bge-large-zh-v1.5',
        'device': 'cuda',
        'batch_size': 32,
        'normalize': True,
        'cache_dir': '.cache/models',
        'models': {
            'bge-large-zh-v1.5': {
                'model_id': 'BAAI/bge-large-zh-v1.5',
                'mirror_ids': ['AI-ModelScope/bge-large-zh-v1.5'],
                'query_prefix': '为这个句子生成表示以用于检索相关文章：',
                'dim': 1024,
                'max_length': 512,
            },
            'bge-m3': {
                'model_id': 'BAAI/bge-m3',
                'mirror_ids': ['AI-ModelScope/bge-m3'],
                'query_prefix': '',
                'dim': 1024,
                'max_length': 8192,
            },
            'qwen3-embedding-0.6b': {
                'model_id': 'Qwen/Qwen3-Embedding-0.6B',
                'mirror_ids': ['Qwen/Qwen3-Embedding-0.6B'],
                'query_prefix': 'Given a web search query, retrieve relevant passages that answer the query: ',
                'dim': 1024,
                'max_length': 32768,
            },
        },
    },
    'paths': {
        'index_dir': 'data/indexes',
        'eval_path': 'data/eval_questions.json',
    },
    'retrieval': {
        'top_k': 3,
    },
}


def _merge(base, override):
    out = deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, data, root):
        self._data = data
        self.root = root

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def path(self, key):
        """把配置里的相对路径解析成绝对路径（相对于项目根目录）。"""
        return os.path.join(self.root, self._data['paths'][key])

    def model(self, alias=None):
        alias = alias or self._data['embedder']['active']
        models = self._data['embedder']['models']
        if alias not in models:
            raise KeyError('未知模型别名 %r，可选：%s' % (alias, ', '.join(models)))
        return alias, models[alias]

    def to_dict(self):
        return deepcopy(self._data)


def load(root=None, overrides=None):
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, 'config.json')
    data = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    return Config(_merge(DEFAULT, data), root)
