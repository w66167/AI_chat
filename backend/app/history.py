# -*- coding: utf-8 -*-
"""提问记录：登录并绑定了在校身份的用户，换设备也能看到自己问过什么。

游客不存（FR-05：游客不留存个人历史）。每个用户只保留最近若干条，
存的是问题、回答和引用的条文编号——不含任何个人业务数据。
"""
import json
import os
import threading
import time

from .config import BACKEND_DIR

PATH = os.path.join(BACKEND_DIR, 'data', 'history.json')
_lock = threading.Lock()
_data = None


def _load():
    global _data
    if _data is None:
        try:
            with open(PATH, encoding='utf-8') as f:
                _data = json.load(f)
        except (OSError, ValueError):
            _data = {}
    return _data


def _save():
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(_data, f, ensure_ascii=False)
    os.replace(tmp, PATH)


def append(user_id, question, resp, limit=100):
    record = {
        'id': resp.get('trace_id', ''), 'ts': time.strftime('%Y-%m-%d %H:%M'),
        'question': question, 'answer': resp.get('answer', ''),
        'behavior': resp.get('behavior', ''), 'answer_mode': resp.get('answer_mode', ''),
        'citations': [{'chunk_id': c['chunk_id'], 'doc': c['doc'], 'article': c['article'],
                       'page_start': c['page_start']} for c in resp.get('citations') or []],
    }
    with _lock:
        data = _load()
        data[user_id] = (data.get(user_id) or [])[-(limit - 1):] + [record]
        _save()
    return record


def list_for(user_id, limit=50):
    with _lock:
        return list(reversed((_load().get(user_id) or [])[-limit:]))


def clear(user_id):
    with _lock:
        data = _load()
        if user_id in data:
            del data[user_id]
            _save()


def reset_for_tests(path):
    global _data, PATH
    with _lock:
        _data, PATH = None, path
