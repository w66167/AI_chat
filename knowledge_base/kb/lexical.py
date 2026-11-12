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


def faq_map(entries, chunks):
    """问答条目 → 它引用的那条条文。返回 {chunk_id: '标题 别名 别名 …'}。

    问答条目的标题和别名是「人会怎么问」，条文正文是「制度怎么写」，两者用词差得很远
    （「挂科」vs「考核不及格」）。把问法挂到对应条文上参与检索，等于一份免费的同义词表。
    """
    out = {}
    for e in entries or []:
        ref = e.get('handbook_ref') or {}
        for c in chunks:
            if c.doc != ref.get('doc'):
                continue
            if ref.get('article') and c.article != ref.get('article'):
                continue
            if not (c.page_start <= (ref.get('page') or 0) <= c.page_end):
                continue
            text = ' '.join([e.get('title', '')] + list(e.get('aliases') or []))
            out[c.id] = (out.get(c.id, '') + ' ' + text).strip()
            break
    return out


class FieldedBM25Retriever:
    """正文 + 标题 + 常见问法三路 BM25 加权求和。不需要 numpy / torch / 显卡。

    用途：向量模型不可用（没装环境、没建索引、没有显卡的服务器）时的保底检索，
    接口与向量检索器一致（search 返回 [(chunk_id, score)]，另带 chunks 字典）。

    在 150 条评测集上（110 道有标准答案）：
        仅正文 BM25                Top-3 73.6%
        + 0.4×标题 + 0.6×常见问法   Top-3 77.3%，Top-5 83.6%
    比向量+重排（89.1%）低，所以它是保底而不是首选。

    分数没有上界，confidence() 用一条 S 形曲线把它压到 0~1，
    这样上层「低于阈值拒答」的策略两条路径可以共用。
    """

    def __init__(self, chunks_by_id, chunks, faq=None, w_title=0.4, w_faq=0.6,
                 exclude_articles=('导语',), midpoint=9.0, scale=2.5, name='bm25-fielded'):
        self.name = name
        self.chunks = chunks_by_id
        self.midpoint, self.scale = midpoint, scale
        self.w_title, self.w_faq = w_title, w_faq
        usable = [c for c in chunks if c.article not in (exclude_articles or ())]
        faq = faq or {}
        self._ids = [c.id for c in usable]
        self._text = BM25Retriever(chunks_by_id, [(c.id, c.text) for c in usable])
        self._title = BM25Retriever(chunks_by_id,
                                    [(c.id, '%s %s' % (c.doc, c.chapter)) for c in usable])
        self._has_faq = [bool(faq.get(c.id)) for c in usable]
        self._faq = BM25Retriever(chunks_by_id, [(c.id, faq.get(c.id) or '无') for c in usable])

    def search(self, query, k=3):
        text = self._text.score_all(query)
        title = self._title.score_all(query)
        faq = self._faq.score_all(query)
        scored = []
        for i, cid in enumerate(self._ids):
            s = text[i][1] + self.w_title * title[i][1]
            if self._has_faq[i]:
                s += self.w_faq * faq[i][1]
            scored.append((cid, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]

    def confidence(self, score):
        x = (float(score) - self.midpoint) / self.scale
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))
