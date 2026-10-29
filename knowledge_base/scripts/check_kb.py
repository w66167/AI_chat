# -*- coding: utf-8 -*-
"""校验问答条目的可追溯性与字段完整性。

核心检查：每条问答的 handbook_ref 必须能在切块语料里定位到唯一的条，
否则这条答案就是「无出处的生成内容」，不能发布。
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')

REQUIRED = ['id', 'category', 'title', 'answer', 'source', 'scope', 'version', 'status']


def load_chunks():
    path = os.path.join(DATA, 'handbook_chunks.jsonl')
    return [json.loads(line) for line in open(path, encoding='utf-8')]


def longest_common(a, b):
    """最长公共子串长度（答案多为改写，用字符级重合度做题源一致性代理）。"""
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def main():
    kb = json.load(open(os.path.join(DATA, 'handbook_qa.json'), encoding='utf-8'))
    chunks = load_chunks()
    entries = kb['entries']
    errors, warns = [], []

    seen_ids, seen_titles = set(), {}
    for e in entries:
        eid = e.get('id', '?')
        for key in REQUIRED:
            if not str(e.get(key, '')).strip():
                errors.append('%s 缺少字段 %s' % (eid, key))
        if eid in seen_ids:
            errors.append('%s 编号重复' % eid)
        seen_ids.add(eid)
        if e['title'] in seen_titles:
            errors.append('%s 标题与 %s 重复' % (eid, seen_titles[e['title']]))
        seen_titles[e['title']] = eid
        if e['category'] not in kb['categories']:
            errors.append('%s 分类 %s 不在 categories 中' % (eid, e['category']))
        if e['status'] not in ('draft', 'pending', 'published', 'disabled'):
            errors.append('%s 状态 %s 不合法' % (eid, e['status']))
        if len(e['answer']) < 20:
            warns.append('%s 答案过短（%d 字）' % (eid, len(e['answer'])))
        if len(e.get('aliases') or []) < 2:
            warns.append('%s 同义问法少于 2 条，检索命中率会偏低' % eid)

        ref = e.get('handbook_ref') or {}
        hits = [c for c in chunks
                if c['doc'] == ref.get('doc')
                and (not ref.get('article') or c['article'] == ref['article'])]
        if not ref.get('doc'):
            errors.append('%s 未登记 handbook_ref.doc' % eid)
            continue
        if not hits:
            errors.append('%s 的出处无法在切块语料中定位：%s %s' % (eid, ref.get('doc'), ref.get('article')))
            continue
        page = ref.get('page')
        exact = [c for c in hits if c['page_start'] <= page <= c['page_end']]
        if not exact:
            errors.append('%s 登记的页码 %s 不在出处条文的页码范围 %s—%s 内'
                          % (eid, page, hits[0]['page_start'], hits[0]['page_end']))
        # source 字符串里的「第N页」应与 handbook_ref.page 一致
        m = re.search(r'第(\d+)页', e['source'])
        if m and page and int(m.group(1)) != int(page):
            errors.append('%s source 写的是第%s页，handbook_ref 是第%s页' % (eid, m.group(1), page))
        # 答案与出处条文应有足够重合（防止张冠李戴）：取最长公共子串长度作代理指标
        body = re.sub(r'\s+', '', ''.join(c['text'] for c in hits))
        ans = re.sub(r'\s+', '', e['answer'])
        if longest_common(ans, body) < 8:
            warns.append('%s 答案与出处原文几乎无重合，请人工核对' % eid)

    print('条目 %d 条，切块 %d 块' % (len(entries), len(chunks)))
    print('分类分布：' + '，'.join('%s %d' % (c, sum(1 for e in entries if e['category'] == c))
                             for c in kb['categories']))
    print('覆盖手册文档 %d 篇' % len({e['handbook_ref']['doc'] for e in entries}))
    for w in warns:
        print('[警告]', w)
    for x in errors:
        print('[错误]', x)
    print('结果：%s（错误 %d，警告 %d）' % ('通过' if not errors else '未通过', len(errors), len(warns)))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
