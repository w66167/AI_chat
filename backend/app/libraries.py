# -*- coding: utf-8 -*-
"""知识库注册表与身份路由（FR-01 / FR-16）。

唯一数据源：`knowledge_base/data/libraries.json`。
小程序端的 `miniprogram/data/libraries.js` 由 `knowledge_base/scripts/export_libraries.py`
从同一份 JSON 生成，因此「后端检索了哪个库」和「前端显示了哪个库」不会各说各话。

这里只做两件事，检索本身仍在 knowledge_base 里：
    1. 身份 → 能访问哪些知识库（按知识库的 audience 反查）
    2. 知识块 → 属于哪个知识库（按各知识库声明的 chunks_path 反查；
       多个知识库共用一份语料时，再按 doc_index=[起, 止] 划分各自的文件范围）
"""
import json
import os

from .config import KB_DIR

_REGISTRY = None
_CHUNK_OWNER = None


def _registry_path():
    return os.path.join(KB_DIR, 'data', 'libraries.json')


def registry():
    global _REGISTRY
    if _REGISTRY is None:
        with open(_registry_path(), encoding='utf-8') as f:
            _REGISTRY = json.load(f)
    return _REGISTRY


def libraries():
    return registry()['libraries']


def library(kb_id):
    for item in libraries():
        if item['id'] == kb_id:
            return item
    return None


def for_identity(identity_type):
    """该身份能访问的全部知识库（含还没建索引的）。"""
    return [item for item in libraries() if identity_type in item['audience']]


def searchable_for(identity_type):
    """该身份能访问、且已经建好索引的知识库——这些才是本次真正能检索的。"""
    return [item for item in for_identity(identity_type) if item.get('index_ready')]


def pending_for(identity_type):
    """该身份能访问、但索引尚未建设的知识库。

    要如实告诉用户「这次没查这个库」，否则就是拿别的库冒充全部知识。
    """
    return [item for item in for_identity(identity_type) if not item.get('index_ready')]


def brief(item):
    """给接口返回用的知识库摘要。"""
    return {
        'id': item['id'], 'name': item['name'], 'version': item['version'],
        'content_status': item.get('content_status', 'ready'),
        'index_ready': bool(item.get('index_ready')),
        'audience': item.get('audience', []),
    }


def citation_kb(kb_id):
    item = library(kb_id)
    if not item:
        return None
    return {'id': item['id'], 'name': item['name'], 'version': item['version'],
            'updated_at': item.get('updated_at', ''), 'index_ready': bool(item.get('index_ready'))}


def chunk_owner_map():
    """chunk_id → 知识库 id。

    读一遍各知识库声明的 chunks_path。语料文件不存在（例如教职工手册内容还没补）
    就跳过，不影响其它知识库。知识库声明了 doc_index=[起, 止] 时，只认领这个范围内的文件
    ——学生手册 PDF 里前三份是教育部规章（游客可查），后面 25 份是校内规章（登录身份可查）。
    """
    global _CHUNK_OWNER
    if _CHUNK_OWNER is None:
        owner = {}
        for item in libraries():
            rel = item.get('chunks_path')
            if not rel:
                continue
            path = rel if os.path.isabs(rel) else os.path.join(KB_DIR, rel)
            if not os.path.exists(path):
                continue
            span = item.get('doc_index') or None
            with open(path, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        if span and not (span[0] <= int(row.get('doc_index') or 0) <= span[1]):
                            continue
                        owner[row['id']] = item['id']
                    except (ValueError, KeyError, TypeError):
                        continue
        _CHUNK_OWNER = owner
    return _CHUNK_OWNER


def kb_of_chunk(chunk_id):
    return chunk_owner_map().get(chunk_id)


def filter_hits(hits, allowed_ids):
    """只保留属于 allowed_ids 这些知识库的命中。

    注册表里一个知识块都没登记时（例如注册表被改坏 / 语料路径写错），
    不静默清空结果——那样会变成「什么都查不到」这种最难排查的故障。
    """
    owner = chunk_owner_map()
    if not owner:
        return list(hits)
    return [item for item in hits if owner.get(item[0]) in allowed_ids]
