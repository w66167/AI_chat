# -*- coding: utf-8 -*-
"""HTTP 服务：标准库 ThreadingHTTPServer，路由与会话/策略层解耦。

契约（字段定义见 schemas.py；换 FastAPI 时只需替换本文件的 handler）：
    GET  /v1/health                 服务状态：检索走哪条路径、生成模型是否启用、登录方式
    POST /v1/auth/login             登录（微信 code 或开发模式设备号）→ 令牌
    GET  /v1/me                     当前用户、身份、可查的知识库
    POST /v1/me/identity            绑定 / 解除身份
    POST /v1/ask                    问答
    POST /v1/feedback               反馈
    GET  /v1/suggestions            示例问题（按身份）
    GET  /v1/handbook/catalog       手册目录（按身份）
    GET  /v1/handbook/doc?index=    一份文件的条文列表
    GET  /v1/handbook/article?id=   一条条文原文
    GET  /v1/handbook/search?q=     条文关键词搜索
    GET  /v1/history                我的提问记录（需登录身份）
    POST /v1/history/clear          清空我的提问记录
    GET  /docs

身份规则：所有接口都从 Authorization: Bearer <令牌> 推导身份，没带令牌一律按游客。
请求体里的 scope.identity_type 只在 auth.trust_client_identity 为真时才生效（本机测试用）。
"""
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import answer, auth, deps, handbook, history, libraries, llm, session

START_TS = time.time()
FEEDBACK_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'data', 'feedback.jsonl')
CORS_HEADERS = 'Content-Type, Authorization'


class Handler(BaseHTTPRequestHandler):
    server_version = 'CampusQA/0.2'
    protocol_version = 'HTTP/1.1'

    # ---------------------------------------------------------------- 基础

    def log_message(self, fmt, *args):
        print('[%s] %s' % (time.strftime('%H:%M:%S'), fmt % args), flush=True)

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', CORS_HEADERS)
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code, err_code, message, trace_id=''):
        self._send(code, {'code': err_code, 'message': message, 'trace_id': trace_id})

    def _body(self):
        """请求体（JSON 对象）。do_POST 已经把它读完并缓存，这里只是取出来。"""
        if self._payload_error:
            raise ValueError(self._payload_error)
        return self._payload

    def _read_body(self):
        """读请求体。同时支持 Content-Length 与 Transfer-Encoding: chunked
        （Node 的 http.request 默认走 chunked，wx.request 走 Content-Length，两种都要兼容）。"""
        encoding = (self.headers.get('Transfer-Encoding') or '').lower()
        if 'chunked' in encoding:
            chunks = []
            while True:
                line = self.rfile.readline(65536).strip()
                if not line:
                    continue
                size = int(line.split(b';')[0], 16)
                if size == 0:
                    self.rfile.readline(65536)      # 丢弃结尾空行
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.read(2)                  # CRLF
            raw = b''.join(chunks)
        else:
            length = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(length) if length else b''
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError('请求体不是合法 JSON')
        if not isinstance(data, dict):
            raise ValueError('请求体必须是 JSON 对象')
        return data

    def _query(self):
        parsed = urllib.parse.urlsplit(self.path)
        return parsed.path, {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

    def _user(self):
        """没带令牌 → None（游客）。带了但无效（过期、被改过）→ 401，让客户端重新登录。

        不能把无效令牌悄悄当成游客：那样已绑定身份的用户令牌一过期，
        就会无声地降级成游客、查不到校内规章，而客户端收到的是 200，不知道该重新登录。"""
        user = auth.user_from_headers(self.headers)
        if user is None and (self.headers.get('Authorization') or '').strip():
            raise auth.AuthError('TOKEN_INVALID', '登录已失效，请重新登录', 401)
        return user

    def _identity(self, user, raw=None):
        """身份只认令牌。没登录就是游客——除非显式打开了 trust_client_identity（本机测试）。"""
        if user:
            return user['identity_type']
        cfg = deps.get_config()
        if (cfg.get('auth') or {}).get('trust_client_identity') and raw:
            claimed = ((raw.get('scope') or {}).get('identity_type') or 'guest')
            if claimed in ('guest', 'student', 'teacher', 'staff'):
                return claimed
        return 'guest'

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', CORS_HEADERS)
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Content-Length', '0')
        self.end_headers()

    # ---------------------------------------------------------------- 路由

    GET_ROUTES = {
        '/v1/health': 'health', '/v1/me': 'me', '/v1/suggestions': 'suggestions',
        '/v1/handbook/catalog': 'hb_catalog', '/v1/handbook/doc': 'hb_doc',
        '/v1/handbook/article': 'hb_article', '/v1/handbook/search': 'hb_search',
        '/v1/history': 'history_list', '/docs': 'docs',
    }
    POST_ROUTES = {
        '/v1/ask': 'ask', '/v1/feedback': 'feedback', '/v1/auth/login': 'login',
        '/v1/me/identity': 'bind_identity', '/v1/history/clear': 'history_clear',
    }

    def _dispatch(self, routes):
        path, query = self._query()
        name = routes.get(path.rstrip('/') or '/')
        if not name:
            return self._error(404, 'NOT_FOUND', '未知路径 %s' % path)
        try:
            return getattr(self, name)(query)
        except auth.AuthError as e:
            return self._error(e.status, e.code, e.message)
        except ValueError as e:
            return self._error(400, 'BAD_REQUEST', str(e))
        except Exception as e:           # 任何未预料的错误都要回 JSON，小程序才能按 code 处理
            return self._error(500, 'INTERNAL_ERROR', '处理失败：%s' % str(e)[:160])

    _payload, _payload_error = {}, ''

    def do_GET(self):
        self._payload, self._payload_error = {}, ''
        self._dispatch(self.GET_ROUTES)

    def do_POST(self):
        # 不管哪个接口、会不会用到，都先把请求体读完。连接是复用的（HTTP/1.1 keep-alive）：
        # 请求体留在缓冲区里，会被当成下一个请求的开头，对方就会收到莫名其妙的 501。
        # 鉴权失败、路径不存在这些提前返回的情况尤其容易漏。
        self._payload, self._payload_error = {}, ''
        try:
            self._payload = self._read_body()
        except ValueError as e:
            self._payload_error = str(e)
        self._dispatch(self.POST_ROUTES)

    # ---------------------------------------------------------------- 状态

    def health(self, query):
        cfg = deps.get_config()
        state = deps.status()
        payload = {'status': 'ok' if state['ready'] else 'warming',
                   'uptime_s': round(time.time() - START_TS, 1),
                   'corpus_version': cfg.kb['corpus']['version'],
                   'model': cfg.kb['embedder']['active'] if state['mode'] == 'vector' else 'bm25',
                   'model_loaded': state['ready'],
                   # retrieval：vector = 向量+重排；lexical = 关键词保底（附原因）
                   'retrieval': state['mode'], 'retrieval_fallback': state['fallback_reason'],
                   'llm': dict(llm.status(cfg), **deps.llm_errors()),
                   'auth_mode': auth.mode(cfg),
                   'chunks': state['chunks'], 'units': 0,
                   'index_fingerprint': '', 'sessions': session.stats()['sessions']}
        if state['error']:
            payload['status'] = 'error'
            payload['error'] = state['error']
        if state['mode'] == 'vector':
            try:
                from kb import retriever as kb_retriever
                alias, spec = cfg.kb.model()
                payload['index_fingerprint'] = kb_retriever.expected_fingerprint(cfg.kb, alias, spec)
            except Exception:
                pass
        self._send(200, payload)

    # ---------------------------------------------------------------- 登录与身份

    def _profile(self, user):
        """用户、身份和它能查的知识库——小程序「我的」页和问答页的顶栏都用这一份。"""
        cfg = deps.get_config()
        identity = user['identity_type'] if user else 'guest'
        return {
            'user': auth.public(user) if user else None,
            'identity_type': identity,
            'auth_mode': auth.mode(cfg),
            'binding': auth.binding_rules(cfg),
            'libraries': [dict(libraries.brief(item),
                               summary=item.get('summary', ''), scope_text=item.get('scope_text', ''),
                               documents=len(item.get('documents') or []),
                               accessible=identity in item['audience'])
                          for item in libraries.libraries()],
        }

    def login(self, query):
        raw = self._body()
        result = auth.login(deps.get_config(), code=str(raw.get('code') or ''),
                            device_id=str(raw.get('device_id') or ''))
        user = auth.get_user(result['user']['id'])
        self._send(200, dict(self._profile(user), token=result['token'],
                             expires_in=result['expires_in']))

    def me(self, query):
        user = self._user()
        if not user:
            raise auth.AuthError('UNAUTHORIZED', '登录已失效，请重新登录', 401)
        self._send(200, self._profile(user))

    def bind_identity(self, query):
        user = self._user()
        if not user:
            raise auth.AuthError('UNAUTHORIZED', '登录已失效，请重新登录', 401)
        raw = self._body()
        auth.bind_identity(deps.get_config(), user['id'],
                           str(raw.get('identity_type') or ''), str(raw.get('code') or ''))
        self._send(200, self._profile(auth.get_user(user['id'])))

    # ---------------------------------------------------------------- 问答

    def ask(self, query):
        t0 = time.perf_counter()
        raw = self._body()
        question = str(raw.get('question') or '').strip()
        if not question:
            return self._error(400, 'EMPTY_QUESTION', 'question 不能为空')
        if len(question) > 500:
            return self._error(400, 'QUESTION_TOO_LONG', 'question 超过 500 字')

        try:
            from .schemas import AskRequest
            req = AskRequest(**{k: v for k, v in raw.items()
                                if k in ('question', 'session_id', 'channel', 'scope', 'history', 'client_ts')})
        except Exception as e:
            return self._error(422, 'VALIDATION_ERROR', str(e).splitlines()[0][:160])

        user = self._user()
        cfg = deps.get_config()
        resp = answer.respond(req, cfg=cfg, identity=self._identity(user, raw))
        resp['latency_ms'] = int((time.perf_counter() - t0) * 1000)
        if resp['behavior'] in ('answer', 'answer_with_caveat') and resp['citations']:
            session.append(resp['session_id'], question, resp['answer'],
                           resp['citations'][0]['chunk_id'], cfg=cfg)
        # 提问记录只给绑定了在校身份的登录用户存；游客不留（FR-05）
        if user and user['identity_type'] != 'guest' and not resp.get('kb_gap'):
            history.append(user['id'], question, resp,
                           limit=int((cfg.get('auth') or {}).get('history_limit', 100)))
        self._send(200, resp)

    def feedback(self, query):
        raw = self._body()
        from .schemas import FeedbackRequest
        try:
            req = FeedbackRequest(**raw)
        except Exception as e:
            return self._error(422, 'VALIDATION_ERROR', str(e).splitlines()[0][:160])

        record = req.dict() if hasattr(req, 'dict') else req.model_dump()
        record['ts'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        user = self._user()
        record['user'] = user['id'] if user else ''
        os.makedirs(os.path.dirname(FEEDBACK_LOG), exist_ok=True)
        with open(FEEDBACK_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
        self._send(200, {'ok': True, 'feedback_id': '%s-%d' % (req.message_id[:12], int(time.time()))})

    def suggestions(self, query):
        self._send(200, handbook.suggestions(self._identity(self._user())))

    # ---------------------------------------------------------------- 手册浏览

    def hb_catalog(self, query):
        self._send(200, handbook.catalog(self._identity(self._user())))

    def hb_doc(self, query):
        try:
            index = int(query.get('index') or 0)
        except ValueError:
            index = 0
        data = handbook.document(self._identity(self._user()), index)
        if not data:
            # 不存在和无权查看给同一个回答，不透露受限文件是否存在
            return self._error(404, 'NOT_AVAILABLE', '这份文件不存在，或当前身份无权查看')
        self._send(200, data)

    def hb_article(self, query):
        data = handbook.article(self._identity(self._user()), query.get('id') or '')
        if not data:
            return self._error(404, 'NOT_AVAILABLE', '这条条文不存在，或当前身份无权查看')
        self._send(200, data)

    def hb_search(self, query):
        keyword = (query.get('q') or '').strip()
        self._send(200, {'query': keyword,
                         'items': handbook.search(self._identity(self._user()), keyword)})

    # ---------------------------------------------------------------- 提问记录

    def _member(self):
        user = self._user()
        if not user:
            raise auth.AuthError('UNAUTHORIZED', '登录已失效，请重新登录', 401)
        if user['identity_type'] == 'guest':
            raise auth.AuthError('IDENTITY_REQUIRED', '绑定在校身份后才会保存提问记录', 403)
        return user

    def history_list(self, query):
        self._send(200, {'items': history.list_for(self._member()['id'])})

    def history_clear(self, query):
        history.clear(self._member()['id'])
        self._send(200, {'ok': True})

    def docs(self, query):
        html = """<!doctype html><meta charset="utf-8">
<title>校园知答 API</title>
<style>body{font:14px/1.7 system-ui;margin:40px;max-width:760px}code{background:#f3f3f3;padding:2px 5px}
pre{background:#f7f7f7;padding:12px;overflow:auto}td{padding:3px 14px 3px 0;vertical-align:top}</style>
<h2>校园知答 API</h2>
<p>基于《杭州电子科技大学学生手册》（2017 年 9 月版，206 页、586 条条文）的问答服务。
身份由登录令牌决定：先 <code>POST /v1/auth/login</code> 拿令牌，之后每个请求带
<code>Authorization: Bearer &lt;令牌&gt;</code>；不带令牌按游客处理。</p>
<table>
<tr><td><code>GET /v1/health</code></td><td>检索路径、生成模型、登录方式</td></tr>
<tr><td><code>POST /v1/auth/login</code></td><td><code>{"code": "wx.login 的 code"}</code>；开发模式用 <code>{"device_id": "..."}</code></td></tr>
<tr><td><code>GET /v1/me</code></td><td>当前用户、身份、可查的知识库</td></tr>
<tr><td><code>POST /v1/me/identity</code></td><td><code>{"identity_type": "student"}</code>（guest / student / teacher）</td></tr>
<tr><td><code>POST /v1/ask</code></td><td><code>{"question": "宿舍几点熄灯"}</code></td></tr>
<tr><td><code>POST /v1/feedback</code></td><td><code>{"session_id","message_id","resolved","score"}</code></td></tr>
<tr><td><code>GET /v1/suggestions</code></td><td>示例问题</td></tr>
<tr><td><code>GET /v1/handbook/catalog</code></td><td>手册目录</td></tr>
<tr><td><code>GET /v1/handbook/doc?index=4</code></td><td>一份文件的条文列表</td></tr>
<tr><td><code>GET /v1/handbook/article?id=hb-510</code></td><td>条文原文</td></tr>
<tr><td><code>GET /v1/handbook/search?q=补考</code></td><td>条文搜索</td></tr>
<tr><td><code>GET /v1/history</code></td><td>我的提问记录</td></tr>
</table>
<p><code>/v1/ask</code> 返回 <code>behavior</code> 五档之一：answer / answer_with_caveat / clarify / refuse_noanswer / refuse_boundary。
<code>answer_mode</code> 为 <code>generated</code> 表示回答由大模型依据条文组织，<code>excerpt</code> 表示直接给条文原文（未配置模型或生成降级）。
每条 <code>citations[]</code> 都能用 <code>chunk_id</code> 到 <code>/v1/handbook/article</code> 查到原文。</p>
"""
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(host='127.0.0.1', port=8000):
    return ThreadingHTTPServer((host, port), Handler)
