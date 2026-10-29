# -*- coding: utf-8 -*-
"""后端配置：复用知识库那份 config.json，不重复定义模型与阈值。

后端只加自己需要的两节（answer_policy / session），其余原样读。
"""
import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_DIR = os.path.join(os.path.dirname(BACKEND_DIR), 'knowledge_base')

# 在模块导入期就把知识库目录放进 sys.path，否则任何 `import kb` 都会失败
if KB_DIR not in sys.path:
    sys.path.insert(0, KB_DIR)

DEFAULTS = {
    'answer_policy': {
        # 置信度低于该值视为“没有可靠依据”，走拒答 + 官方途径（FR-12）
        'refuse_below': 0.42,
        # 低于该值但高于 refuse_below 时，转入澄清/提示确认（FR-11 中间档）
        'clarify_below': 0.55,
        # 第一名与第二名太接近，说明有歧义，先反问
        'clarify_gap': 0.02,
        # 问题短于该长度且只是话题词，先澄清
        'clarify_min_chars': 6,
        # 推荐问法条数（FR-15）
        'max_suggestions': 3,
    },
    'session': {
        'max_turns': 5,          # 每个会话保留最近几轮
        'ttl_seconds': 1800,     # 30 分钟无活动即过期
        'store_guest_history': False,  # FR-05：游客不留存个人历史
    },
}


def _merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, kb, data):
        self.kb = kb
        self.data = data

    def __getitem__(self, key):
        if key in self.data:
            return self.data[key]
        return self.kb[key]

    def get(self, key, default=None):
        try:
            return self[key]
        except Exception:
            return default


def load():
    from kb import config as kb_config

    kb = kb_config.load(KB_DIR)
    path = os.path.join(BACKEND_DIR, 'config.json')
    data = {}
    if os.path.exists(path):
        # utf-8-sig：Windows 下用 PowerShell / 记事本保存会带 BOM，普通 utf-8 会解析失败
        with open(path, encoding='utf-8-sig') as f:
            data = json.load(f)
    return Config(kb, _merge(DEFAULTS, data))
