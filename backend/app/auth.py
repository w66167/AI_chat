# -*- coding: utf-8 -*-
"""登录与身份：微信登录识别「是谁」，身份绑定决定「能查什么」。

两件事分开：
  登录   wx.login 的 code → 微信 jscode2session → openid → 本服务签发的令牌
  身份   用户在令牌下绑定 学生 / 教师（行政人员）；没绑定就是游客

问答接口从令牌推导身份，不再相信客户端自己上报的 identity_type
（之前游客把请求里的身份改成 teacher 就能查教师库，见需求文档 FR-02）。

两种运行方式，按有没有配置小程序密钥自动选择：
  wechat  配了 wechat_appid + wechat_secret：走真实微信登录
  dev     没配：按客户端上报的设备号发一个本地账号。只用于开发者工具联调，
          任何人换个设备号就是新账号，不能当成安全认证。

身份绑定目前是「自行声明」：学生直接绑定，教师需要口令（配置了 teacher_code 时）。
真正的在校身份核验要接学校统一身份认证，这里留了 verified 字段和绑定入口。
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import BACKEND_DIR

DATA_DIR = os.path.join(BACKEND_DIR, 'data')
USERS_PATH = os.path.join(DATA_DIR, 'users.json')
KEY_PATH = os.path.join(DATA_DIR, 'token.key')
WECHAT_URL = 'https://api.weixin.qq.com/sns/jscode2session'
BINDABLE = ('guest', 'student', 'teacher')

_lock = threading.Lock()
_users = None
_key = None


class AuthError(Exception):
    def __init__(self, code, message, status=400):
        Exception.__init__(self, message)
        self.code, self.message, self.status = code, message, status


# ---------------------------------------------------------------- 配置

def mode(cfg):
    return 'wechat' if (cfg.secret('wechat_appid') and cfg.secret('wechat_secret')) else 'dev'


def _auth_cfg(cfg):
    return cfg.get('auth') or {}


# ---------------------------------------------------------------- 用户存储

def _load():
    global _users
    if _users is None:
        try:
            with open(USERS_PATH, encoding='utf-8') as f:
                _users = json.load(f)
        except (OSError, ValueError):
            _users = {}
    return _users


def _save():
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = USERS_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(_users, f, ensure_ascii=False, indent=1)
    os.replace(tmp, USERS_PATH)


def _public(user):
    return {'id': user['id'], 'identity_type': user['identity_type'],
            'verified': bool(user.get('verified')), 'bound_at': user.get('bound_at') or '',
            'created_at': user.get('created_at') or ''}


def _upsert(user_id, source):
    with _lock:
        users = _load()
        user = users.get(user_id)
        if not user:
            user = {'id': user_id, 'identity_type': 'guest', 'verified': False,
                    'source': source, 'created_at': time.strftime('%Y-%m-%d %H:%M:%S')}
            users[user_id] = user
            _save()
        return dict(user)


def get_user(user_id):
    with _lock:
        user = _load().get(user_id)
        return dict(user) if user else None


# ---------------------------------------------------------------- 令牌

def _secret_key():
    """签名密钥：首次启动生成并落盘，重启后旧令牌仍然有效。"""
    global _key
    if _key is None:
        with _lock:
            if _key is None:
                try:
                    with open(KEY_PATH, 'rb') as f:
                        _key = f.read()
                except OSError:
                    _key = b''
                if len(_key) < 32:
                    _key = secrets.token_bytes(32)
                    os.makedirs(DATA_DIR, exist_ok=True)
                    with open(KEY_PATH, 'wb') as f:
                        f.write(_key)
    return _key


def _sign(payload):
    return hmac.new(_secret_key(), payload.encode('utf-8'), hashlib.sha256).hexdigest()[:40]


def issue_token(user_id, ttl_seconds):
    uid = base64.urlsafe_b64encode(user_id.encode('utf-8')).decode('ascii').rstrip('=')
    payload = '%s.%d' % (uid, int(time.time()) + int(ttl_seconds))
    return '%s.%s' % (payload, _sign(payload))


def verify_token(token):
    """返回用户（dict）或 None。过期、被改过、用户不存在都算无效。"""
    try:
        uid, exp, sig = (token or '').split('.')
        payload = '%s.%s' % (uid, exp)
        if not hmac.compare_digest(sig, _sign(payload)) or int(exp) < time.time():
            return None
        user_id = base64.urlsafe_b64decode(uid + '=' * (-len(uid) % 4)).decode('utf-8')
    except (ValueError, UnicodeDecodeError):
        return None
    return get_user(user_id)


def user_from_headers(headers):
    value = headers.get('Authorization') or ''
    if not value.lower().startswith('bearer '):
        return None
    return verify_token(value[7:].strip())


# ---------------------------------------------------------------- 登录

def _wechat_openid(cfg, code):
    query = urllib.parse.urlencode({
        'appid': cfg.secret('wechat_appid'), 'secret': cfg.secret('wechat_secret'),
        'js_code': code, 'grant_type': 'authorization_code'})
    try:
        with urllib.request.urlopen('%s?%s' % (WECHAT_URL, query), timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AuthError('WECHAT_UNAVAILABLE', '微信登录服务暂时不可用：%s' % str(e)[:80], 502)
    if data.get('errcode'):
        raise AuthError('WECHAT_LOGIN_FAILED',
                        '微信登录失败（%s）：%s' % (data.get('errcode'), data.get('errmsg', '')), 401)
    openid = data.get('openid')
    if not openid:
        raise AuthError('WECHAT_LOGIN_FAILED', '微信没有返回 openid', 401)
    return openid


def login(cfg, code='', device_id=''):
    """登录并签发令牌。返回 {'token', 'expires_in', 'user', 'auth_mode'}。"""
    current = mode(cfg)
    if current == 'wechat':
        if not code:
            raise AuthError('CODE_REQUIRED', '缺少微信登录凭证 code')
        user_id = 'wx-' + _wechat_openid(cfg, code)
    else:
        device_id = (device_id or '').strip()
        if not (8 <= len(device_id) <= 64):
            raise AuthError('DEVICE_REQUIRED', '开发模式登录需要 8–64 位的 device_id')
        user_id = 'dev-' + hashlib.sha1(device_id.encode('utf-8')).hexdigest()[:20]
    user = _upsert(user_id, current)
    ttl = int(_auth_cfg(cfg).get('token_ttl_days', 30)) * 86400
    return {'token': issue_token(user_id, ttl), 'expires_in': ttl,
            'user': _public(user), 'auth_mode': current}


# ---------------------------------------------------------------- 身份绑定

def binding_rules(cfg):
    """告诉客户端每种身份怎么绑定，界面据此决定要不要弹口令输入框。"""
    return {'student': 'self',
            'teacher': 'code' if cfg.secret('teacher_code') else 'self',
            'verified_by_school': False}


def bind_identity(cfg, user_id, identity_type, code=''):
    if identity_type not in BINDABLE:
        raise AuthError('BAD_IDENTITY', '不支持的身份类型')
    expected = cfg.secret('teacher_code')
    if identity_type == 'teacher' and expected:
        if not hmac.compare_digest(str(code or ''), str(expected)):
            raise AuthError('BAD_CODE', '教师身份口令不正确', 403)
    with _lock:
        users = _load()
        user = users.get(user_id)
        if not user:
            raise AuthError('NO_USER', '用户不存在，请重新登录', 401)
        user['identity_type'] = identity_type
        # 自行声明的身份不是「已核验」：接入学校统一身份认证后由那边置 True
        user['verified'] = False
        user['bound_at'] = time.strftime('%Y-%m-%d %H:%M:%S') if identity_type != 'guest' else ''
        _save()
        return _public(user)


def public(user):
    return _public(user)


def reset_for_tests(users_path=None, key_path=None):
    """测试用：把存储指到临时文件，避免污染真实数据。"""
    global _users, _key, USERS_PATH, KEY_PATH
    with _lock:
        _users, _key = None, None
        if users_path:
            USERS_PATH = users_path
        if key_path:
            KEY_PATH = key_path
