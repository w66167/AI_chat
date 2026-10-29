# -*- coding: utf-8 -*-
"""关键词检索（BM25，二元组）：作为对照基线。

与向量检索实现同一个 Retriever 接口，因此可以用同一套评测代码打分。
用二元组而不是分词，是因为中文分词会把「校园卡」切成「校园/卡」、
把「转专业」切成「转/专业」，反而损失检索信号；二元组没有这个问题。
"""
import math
import re
from collections import Counter

PUNCT = re.compile(r'[\s，。！？、,.!?：:；;“”"\'（）()《》【】—…]')


def norm(text):
    return PUNCT.sub('', str(text or '')).lower()


def bigrams(text):
    t = norm(text)
    return [t[i:i + 2] for i in range(len(t) - 1)]


class BM25Retriever:
    def __init__(self, chunks_by_id, docs, name='bm25-bigram', k1=1.2, b=0.75):
        """docs: [(chunk_id, text)]，按引用单元（整条）建索引。"""
        self.name = name
        self.chunks = chunks_by_id
        self.k1, self.b = k1, b
        self.ids, self.tfs, self.lens = [], [], []
        df = Counter()
        for cid, text in docs:
            tf = Counter(bigrams(text))
            self.ids.append(cid)
            self.tfs.append(tf)
            self.lens.append(sum(tf.values()))
            for term in tf:
                df[term] += 1
        n = len(self.ids)
        self.avgdl = sum(self.lens) / max(n, 1)
        self.idf = {t: math.log((n - d + 0.5) / (d + 0.5) + 1) for t, d in df.items()}

    def score_all(self, query):
        q = bigrams(query)
        out = []
        for cid, tf, dl in zip(self.ids, self.tfs, self.lens):
            s = 0.0
            for term in q:
                f = tf.get(term)
                if not f:
                    continue
                s += self.idf.get(term, 0.0) * f * (self.k1 + 1) / (
                    f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out.append((cid, s))
        return out

    def search(self, query, k=3):
        scored = sorted(self.score_all(query), key=lambda x: -x[1])
        return scored[:k]
