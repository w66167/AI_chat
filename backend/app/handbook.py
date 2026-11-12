# -*- coding: utf-8 -*-
"""手册浏览：目录、文件、条文原文与关键词搜索。

问答给的是「整理过的回答」，这里给的是「原文」。两者互为出口：
回答里的每条引用都能点进条文原文，条文页也能回到问答继续问。

可见范围和问答完全一致——都由 libraries 按身份决定：
游客只能看到国家教育法规那三份文件，学生手册的校内规章要登录并绑定在校身份。
"""
import json
import os
import re

from . import libraries
from .config import KB_DIR

# 手册 28 份文件的分类（按 handbook_docs.json 的 index）。手册目录本身没有分类，
# 这里按事项归并，方便在手机上找。
CATEGORIES = [
    ('国家法规', [1, 2, 3]),
    ('学籍与成绩', [4, 5, 6, 7, 13, 14]),
    ('毕业与学位', [8, 16]),
    ('纪律与申诉', [9, 10, 11, 12, 18]),
    ('课外与学分', [15, 17, 28]),
    ('奖励与资助', [20, 21, 22, 23, 24, 25]),
    ('校园生活', [19, 26, 27]),
]

# 游客能查的只有国家法规，问答条目（handbook_qa.json）都是校内规章，所以单独给几个问题。
GUEST_QUESTIONS = ['对学校的处分不服可以申诉吗？', '学生在校期间受伤，学校要承担责任吗？',
                   '什么情况下学校可以给予退学处理？', '休学期间还算在校学生吗？']

_state = {'chunks': None, 'docs': None, 'by_id': None, 'order': None, 'qa': None, 'bm25': None}


def _load():
    if _state['chunks'] is None:
        chunks = []
        with open(os.path.join(KB_DIR, 'data', 'handbook_chunks.jsonl'), encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    chunks.append(json.loads(line))
        with open(os.path.join(KB_DIR, 'data', 'handbook_docs.json'), encoding='utf-8') as f:
            docs = json.load(f)['docs']
        _state['chunks'] = chunks
        _state['docs'] = docs
        _state['by_id'] = {c['id']: c for c in chunks}
        _state['order'] = {c['id']: i for i, c in enumerate(chunks)}
    return _state


def _qa_entries():
    if _state['qa'] is None:
        try:
            with open(os.path.join(KB_DIR, 'data', 'handbook_qa.json'), encoding='utf-8') as f:
                _state['qa'] = json.load(f)
        except (OSError, ValueError):
            _state['qa'] = {'entries': [], 'categories': []}
    return _state['qa']


def category_of(doc_index):
    for name, indexes in CATEGORIES:
        if doc_index in indexes:
            return name
    return '其他'


def _allowed(identity):
    return {item['id'] for item in libraries.for_identity(identity)}


def _visible(chunk_id, allowed):
    return libraries.kb_of_chunk(chunk_id) in allowed


def _doc_kb(doc):
    """文件属于哪个知识库：看它的第一条条文归谁。"""
    for c in _load()['chunks']:
        if c['doc_index'] == doc['index']:
            return libraries.kb_of_chunk(c['id'])
    return None


def _doc_brief(doc, kb_id):
    kb = libraries.library(kb_id) or {}
    return {'index': doc['index'], 'name': doc['name'], 'category': category_of(doc['index']),
            'page_start': doc['page_start'], 'page_end': doc['page_end'],
            'pages': doc['page_end'] - doc['page_start'] + 1,
            'articles': doc.get('articles') or doc.get('chunks') or 0,
            'chunks': doc.get('chunks') or 0,
            'kb_id': kb_id or '', 'kb_name': kb.get('name', '')}


def catalog(identity):
    """目录：按分类分组的文件清单，只含当前身份能看的；另给出被隐藏的数量用于提示登录。"""
    allowed = _allowed(identity)
    groups, hidden = [], 0
    docs = {d['index']: d for d in _load()['docs']}
    for name, indexes in CATEGORIES:
        items = []
        for index in indexes:
            doc = docs.get(index)
            if not doc:
                continue
            kb_id = _doc_kb(doc)
            if kb_id in allowed:
                items.append(_doc_brief(doc, kb_id))
            else:
                hidden += 1
        if items:
            groups.append({'category': name, 'docs': items})
    return {'groups': groups, 'visible': sum(len(g['docs']) for g in groups), 'hidden': hidden,
            'total': len(docs)}


def _article_brief(c, full=False):
    text = c['text']
    out = {'id': c['id'], 'article': c.get('article') or '', 'chapter': c.get('chapter') or '',
           'section': c.get('section') or '', 'page_start': c['page_start'],
           'page_end': c['page_end'], 'chars': len(text)}
    if full:
        out['text'] = text
    else:
        out['preview'] = text[:60] + ('…' if len(text) > 60 else '')
    return out


def document(identity, index):
    """一份文件的全部条文（预览），按章分组。无权查看或不存在都返回 None——不区分两者，
    避免透露受限文件是否存在。"""
    state = _load()
    doc = next((d for d in state['docs'] if d['index'] == index), None)
    if not doc:
        return None
    kb_id = _doc_kb(doc)
    if kb_id not in _allowed(identity):
        return None
    chapters, current = [], None
    for c in state['chunks']:
        if c['doc_index'] != index:
            continue
        title = c.get('chapter') or ''
        if current is None or current['chapter'] != title:
            current = {'chapter': title, 'articles': []}
            chapters.append(current)
        current['articles'].append(_article_brief(c))
    return {'doc': _doc_brief(doc, kb_id), 'chapters': chapters}


def article(identity, chunk_id):
    state = _load()
    c = state['by_id'].get(chunk_id)
    if not c or not _visible(chunk_id, _allowed(identity)):
        return None
    out = _article_brief(c, full=True)
    kb_id = libraries.kb_of_chunk(chunk_id)
    kb = libraries.library(kb_id) or {}
    out.update({'doc': c['doc'], 'doc_index': c['doc_index'], 'source': c['source'],
                'category': category_of(c['doc_index']),
                'kb': libraries.citation_kb(kb_id), 'scope': kb.get('scope_text', ''),
                'needs_review': bool(c.get('needs_review'))})
    # 上一条 / 下一条：只在同一份文件内翻
    i = state['order'][chunk_id]
    chunks = state['chunks']
    prev_c = chunks[i - 1] if i > 0 and chunks[i - 1]['doc_index'] == c['doc_index'] else None
    next_c = chunks[i + 1] if i + 1 < len(chunks) and chunks[i + 1]['doc_index'] == c['doc_index'] else None
    out['prev'] = {'id': prev_c['id'], 'article': prev_c.get('article') or ''} if prev_c else None
    out['next'] = {'id': next_c['id'], 'article': next_c.get('article') or ''} if next_c else None
    return out


def _snippet(text, terms, width=70):
    pos = -1
    for t in terms:
        pos = text.find(t)
        if pos >= 0:
            break
    if pos < 0:
        return text[:width] + ('…' if len(text) > width else '')
    start = max(0, pos - 18)
    end = min(len(text), start + width)
    return ('…' if start else '') + text[start:end] + ('…' if end < len(text) else '')


def search(identity, query, limit=20):
    """关键词搜索条文原文。整词出现的排前面，其余按二元词 BM25。"""
    query = re.sub(r'\s+', '', query or '')[:40]
    if not query:
        return []
    state = _load()
    if _state['bm25'] is None:
        from kb.lexical import BM25Retriever
        _state['bm25'] = BM25Retriever(None, [(c['id'], '%s %s %s' % (c['doc'], c.get('article') or '', c['text']))
                                              for c in state['chunks']])
    allowed = _allowed(identity)
    scored = []
    for chunk_id, score in _state['bm25'].score_all(query):
        if score <= 0 or not _visible(chunk_id, allowed):
            continue
        c = state['by_id'][chunk_id]
        if query in c['text'] or query in c['doc']:
            score += 100.0
        scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    out = []
    for _, c in scored[:limit]:
        item = _article_brief(c)
        item.update({'doc': c['doc'], 'doc_index': c['doc_index'],
                     'snippet': _snippet(c['text'], [query, query[:2]])})
        out.append(item)
    return out


def suggestions(identity, limit=8):
    """首页和问答页的示例问题。只给当前身份真的能问出答案的。"""
    allowed = _allowed(identity)
    if 'student-handbook' not in allowed:
        return {'questions': GUEST_QUESTIONS[:limit], 'groups': []}
    qa = _qa_entries()
    groups = []
    for category in qa.get('categories') or []:
        titles = [e['title'] for e in qa['entries'] if e.get('category') == category]
        if titles:
            groups.append({'category': category, 'questions': titles})
    # 每个分类轮流取一条，保证首页的几个问题覆盖不同事项
    picked, depth = [], 0
    while len(picked) < limit and any(depth < len(g['questions']) for g in groups):
        for g in groups:
            if depth < len(g['questions']) and len(picked) < limit:
                picked.append(g['questions'][depth])
        depth += 1
    return {'questions': picked, 'groups': groups}
