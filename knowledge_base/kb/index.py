# -*- coding: utf-8 -*-
"""索引层：向量矩阵的保存、加载与指纹校验。

索引是派生产物（可从语料重建），所以不做增量更新，只做整建整载。
指纹不匹配时拒绝加载——防止「换了模型还用旧索引」这种静默错误。
"""
import hashlib
import json
import os
from dataclasses import dataclass

import numpy as np


def fingerprint(model_id, dim, corpus_version, max_chars, normalize, exclude_articles=()):
    """指纹必须覆盖所有影响向量的输入，否则改配置后旧索引会被误判为有效。"""
    raw = '|'.join([str(model_id), str(dim), str(corpus_version),
                    str(max_chars), str(int(normalize)),
                    ','.join(sorted(exclude_articles))])
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


@dataclass
class Index:
    unit_ids: list
    parent_ids: list
    vectors: np.ndarray
    fingerprint: str
    meta: dict

    @property
    def size(self):
        return len(self.unit_ids)

    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez_compressed(
            path,
            unit_ids=np.array(self.unit_ids, dtype=object),
            parent_ids=np.array(self.parent_ids, dtype=object),
            vectors=self.vectors,
            fingerprint=np.array(self.fingerprint),
            meta=np.array(json.dumps(self.meta, ensure_ascii=False)))
        return path

    @classmethod
    def load(cls, path, expect_fingerprint=None):
        if not os.path.exists(path):
            raise FileNotFoundError('索引不存在：%s（先运行 scripts/build_index.py）' % path)
        data = np.load(path, allow_pickle=True)
        fp = str(data['fingerprint'])
        if expect_fingerprint and fp != expect_fingerprint:
            raise RuntimeError(
                '索引指纹不匹配：文件 %s，期望 %s。\n'
                '说明语料或模型配置变了，请删除 %s 后重新建索引。' % (fp, expect_fingerprint, path))
        return cls(unit_ids=[str(x) for x in data['unit_ids']],
                   parent_ids=[str(x) for x in data['parent_ids']],
                   vectors=data['vectors'].astype(np.float32),
                   fingerprint=fp,
                   meta=json.loads(str(data['meta'])))

    def search(self, query_vector, k=3):
        """余弦相似度。向量已归一化时点积即余弦。返回 (unit_id, score) 降序。"""
        q = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        scores = self.vectors @ q
        k = min(k, scores.shape[0])
        idx = np.argpartition(-scores, k - 1)[:k]
        idx = idx[np.argsort(-scores[idx])]
        return [(self.unit_ids[i], float(scores[i])) for i in idx]
