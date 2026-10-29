# -*- coding: utf-8 -*-
"""会话：内存存储，带轮数上限与空闲过期。

刻意不落库：演示环境不需要持久化，且 FR-05 要求游客不留存历史。
接真实认证后，登录用户的会话再迁到 Redis/PG。
"""
import threading
import time
import uuid

_lock = threading.Lock()
_store = {}


def new_id():
    return uuid.uuid4().hex[:16]


def _now():
    return time.time()


def _gc(cfg):
    """清掉过期会话，避免内存无界增长。"""
    ttl = cfg['session']['ttl_seconds']
    dead = [sid for sid, s in _store.items() if _now() - s['updated'] > ttl]
    for sid in dead:
        del _store[sid]


def append(session_id, question, answer, chunk_id='', cfg=None):
    if not cfg or not cfg['session'].get('store_guest_history', False):
        return
    max_turns = cfg['session']['max_turns']
    with _lock:
        _gc(cfg)
        s = _store.get(session_id) or {'turns': [], 'updated': _now()}
        s['turns'].append({'q': question, 'a': answer, 'chunk_id': chunk_id, 'ts': _now()})
        s['turns'] = s['turns'][-max_turns:]
        s['updated'] = _now()
        _store[session_id] = s


def last_question(session_id):
    s = _store.get(session_id)
    if not s or not s['turns']:
        return None
    return s['turns'][-1]['q']


def last_chunk(session_id):
    s = _store.get(session_id)
    if not s or not s['turns']:
        return None
    return s['turns'][-1].get('chunk_id') or None


def stats():
    return {'sessions': len(_store)}
