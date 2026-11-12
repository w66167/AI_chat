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
    # 检索后端：auto = 优先向量+重排，环境或索引不可用时退到关键词检索（不需要显卡）
    'search': {
        'backend': 'auto',       # auto / vector / lexical
    },
    # 关键词检索的分数量纲和重排模型不同，阈值单独一套；中间档（澄清）停用，交给生成层判断
    'lexical_policy': {
        'refuse_below': 0.30,
        'clarify_below': 0.30,
        # 没有大模型把关、直接给条文原文时，门槛提高：关键词检索分不清「相关条文」和
        # 「碰巧有同样字眼的条文」，宁可少答。评测集上（关键词检索 + 条文原文）：
        #   0.30 → 手册里没有的问题拒掉 12/20，命中的问题照常作答 85/85
        #   0.69 → 拒掉 16/20，命中的问题作答 78/85
        'refuse_below_excerpt': 0.69,
    },
    # 生成层：OpenAI 兼容接口。密钥不写在这里，见 Config.secret()。
    'llm': {
        'enabled': True,
        'provider': 'deepseek',  # deepseek / qwen / zhipu；也可以直接填 base_url + model
        'base_url': '',
        'model': '',
        'timeout_seconds': 20,
        'max_tokens': 700,
        'temperature': 0.2,
        'json_mode': True,
        'passages': 5,           # 交给模型的候选条文数（检索前 5 名的召回比前 3 名高约 6 个点）
    },
    'auth': {
        'token_ttl_days': 30,
        # 为真时，没带令牌的请求按请求体里的 scope.identity_type 处理（只给本机测试脚本用）。
        # 线上必须为假：身份只从登录令牌推导。
        'trust_client_identity': False,
        'history_limit': 100,    # 每个用户保留的提问记录条数
    },
}

# 密钥名 → 环境变量名。密钥只从环境变量或 backend/secrets.json 读，不进 config.json、不进版本库。
SECRET_ENV = {
    'llm_api_key': 'CAMPUS_LLM_API_KEY',
    'wechat_appid': 'CAMPUS_WECHAT_APPID',
    'wechat_secret': 'CAMPUS_WECHAT_SECRET',
    'teacher_code': 'CAMPUS_TEACHER_CODE',
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
    def __init__(self, kb, data, secrets=None):
        self.kb = kb
        self.data = data
        self.secrets = secrets or {}

    def secret(self, name):
        """环境变量优先，其次 backend/secrets.json。没配返回空串。"""
        value = os.environ.get(SECRET_ENV.get(name, ''), '')
        return (value or self.secrets.get(name) or '').strip()

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
    secrets = {}
    secrets_path = os.path.join(BACKEND_DIR, 'secrets.json')
    if os.path.exists(secrets_path):
        with open(secrets_path, encoding='utf-8-sig') as f:
            secrets = {k: v for k, v in json.load(f).items() if isinstance(v, str)}
    return Config(kb, _merge(DEFAULTS, data), secrets)
