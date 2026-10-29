# -*- coding: utf-8 -*-
"""语料层：把切块转成「检索单元 Unit」，同时保留「引用单元 Chunk」。

两者分离的原因见 ARCHITECTURE.md：嵌入模型有长度上限，长条文必须拆开才能被
检索到；但用户看到的引用必须仍是完整的一条（带文件、条号、页码）。
"""
import json
import os
import re
from dataclasses import dataclass, field

SENT_END = '。；！？'


@dataclass
class Chunk:
    id: str
    doc: str
    article: str
    source: str
    text: str
    page_start: int = 0
    page_end: int = 0
    chapter: str = ''

    def as_ref(self):
        return {'chunk_id': self.id, 'source': self.source, 'text': self.text,
                'doc': self.doc, 'article': self.article,
                'page_start': self.page_start, 'page_end': self.page_end}


@dataclass
class Unit:
    id: str
    parent_id: str
    part: int
    text: str
    chunk: Chunk = field(repr=False, default=None)


def _split_sentences(text):
    """按中文句末标点切句，标点跟着前一句走。"""
    out, buf = [], ''
    for ch in text:
        buf += ch
        if ch in SENT_END:
            out.append(buf)
            buf = ''
    if buf.strip():
        out.append(buf)
    return out


def split_long_text(text, max_chars, min_chars=40):
    """把超长条文切成不超过 max_chars 的片段，尽量在句子边界断开。"""
    text = re.sub(r'\s+', '', text or '')
    if len(text) <= max_chars:
        return [text]
    sentences = _split_sentences(text)
    parts, buf = [], ''
    for sent in sentences:
        if len(buf) + len(sent) > max_chars and len(buf) >= min_chars:
            parts.append(buf)
            buf = sent
        else:
            buf += sent
    if buf:
        parts.append(buf)
    # 单句仍超长时硬切（法规里少见，但不能静默截断）
    out = []
    for p in parts:
        while len(p) > max_chars:
            out.append(p[:max_chars])
            p = p[max_chars:]
        if p:
            out.append(p)
    return out


def load_chunks(path):
    chunks = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            chunks.append(Chunk(id=d['id'], doc=d.get('doc', ''), article=d.get('article', ''),
                                source=d.get('source', ''), text=d.get('text', ''),
                                page_start=d.get('page_start', 0), page_end=d.get('page_end', 0),
                                chapter=d.get('chapter', '')))
    return chunks


def build_units(chunks, max_chars=500, min_chars=40, exclude_articles=('导语',)):
    """生成检索单元。单块不超长的，unit.id == chunk.id（不制造无谓的间接层）。

    导语块（“XXX管理办法 杭电教[2013]109号为规范……制定本办法”）反复出现主题词，
    却不含任何可回答的内容，在检索里会大量抢占前排（实测「选课分几轮」就命中了导语）。
    它们保留在语料里供溯源，但不进入索引。
    """
    units = []
    for c in chunks:
        if c.article in exclude_articles:
            continue
        pieces = split_long_text(c.text, max_chars, min_chars)
        if len(pieces) == 1:
            units.append(Unit(id=c.id, parent_id=c.id, part=0, text=pieces[0], chunk=c))
        else:
            for i, piece in enumerate(pieces):
                units.append(Unit(id='%s#%d' % (c.id, i), parent_id=c.id, part=i,
                                  text=piece, chunk=c))
    return units


def load_corpus(cfg):
    path = cfg['corpus']['chunks_path']
    if not os.path.isabs(path):
        path = os.path.join(cfg.root, path)
    chunks = load_chunks(path)
    units = build_units(chunks, cfg['corpus']['max_chars'], cfg['corpus']['min_chars'])
    return chunks, units

