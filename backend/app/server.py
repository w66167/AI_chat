# -*- coding: utf-8 -*-
"""HTTP 服务：标准库 ThreadingHTTPServer，路由与会话/策略层解耦。

契约（与 schemas.py 一致，换 FastAPI 时只需替换本文件的三个 handler）：
    GET  /v1/health
    POST /v1/ask
    POST /v1/feedback
    GET  /docs
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import answer, deps, session

START_TS = time.time()
FEEDBACK_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'data', 'feedback.jsonl')


class Handler(BaseHTTPRequestHandler):
    server_version = 'CampusQA/0.1'
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
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code, err_code, message, trace_id=''):
        self._send(code, {'code': err_code, 'message': message, 'trace_id': trace_id})

    def _body(self):
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
            return json.loads(raw.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError('请求体不是合法 JSON')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.end_headers()

    # ---------------------------------------------------------------- 路由

    def do_GET(self):
        if self.path.startswith('/v1/health'):
            return self.health()
        if self.path.startswith('/docs'):
            return self.docs()
        self._error(404, 'NOT_FOUND', '未知路径 %s' % self.path)

    def do_POST(self):
        if self.path.startswith('/v1/ask'):
            return self.ask()
        if self.path.startswith('/v1/feedback'):
            return self.feedback()
        self._error(404, 'NOT_FOUND', '未知路径 %s' % self.path)

    # ---------------------------------------------------------------- 处理

    def health(self):
        cfg = deps.get_config()          # 先导入 config，它负责把 kb 加进 sys.path
        from kb import retriever as kb_retriever
        state = deps.status()
        payload = {'status': 'ok' if state['ready'] else 'warming',
                   'uptime_s': round(time.time() - START_TS, 1),
                   'corpus_version': cfg.kb['corpus']['version'],
                   'model': cfg.kb['embedder']['active'],
                   'model_loaded': state['ready'],
                   'chunks': state['chunks'], 'units': 0,
                   'index_fingerprint': '', 'sessions': session.stats()['sessions']}
        if state['error']:
            payload['status'] = 'error'
            payload['error'] = state['error']
        try:
            alias, spec = cfg.kb.model()
            payload['index_fingerprint'] = kb_retriever.expected_fingerprint(cfg.kb, alias, spec)
        except Exception:
            pass
        self._send(200, payload)

    def ask(self):
        t0 = time.perf_counter()
        try:
            raw = self._body()
        except ValueError as e:
            return self._error(400, 'BAD_REQUEST', str(e))

        question = (raw.get('question') or '').strip()
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

        try:
            resp = answer.respond(req)
        except Exception as e:
            return self._error(500, 'INTERNAL_ERROR', '处理失败：%s' % str(e)[:160])

        resp['latency_ms'] = int((time.perf_counter() - t0) * 1000)
        if resp['behavior'] == 'answer' and resp['citations']:
            session.append(resp['session_id'], question, resp['answer'],
                           resp['citations'][0]['chunk_id'], cfg=deps.get_config())
        self._send(200, resp)

    def feedback(self):
        try:
            raw = self._body()
        except ValueError as e:
            return self._error(400, 'BAD_REQUEST', str(e))
        from .schemas import FeedbackRequest
        try:
            req = FeedbackRequest(**raw)
        except Exception as e:
            return self._error(422, 'VALIDATION_ERROR', str(e).splitlines()[0][:160])

        record = req.dict() if hasattr(req, 'dict') else req.model_dump()
        record['ts'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        os.makedirs(os.path.dirname(FEEDBACK_LOG), exist_ok=True)
        with open(FEEDBACK_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
        self._send(200, {'ok': True, 'feedback_id': '%s-%d' % (req.message_id[:12], int(time.time()))})

    def docs(self):
        html = """<!doctype html><meta charset="utf-8">
<title>校园知答 API</title>
<style>body{font:14px/1.7 system-ui;margin:40px;max-width:760px}code{background:#f3f3f3;padding:2px 5px}
pre{background:#f7f7f7;padding:12px;overflow:auto}</style>
<h2>校园知答 API</h2>
<p>基于《杭州电子科技大学学生手册》206 页 / 579 个检索单元的问答服务。</p>
<h3>GET /v1/health</h3><pre>curl http://127.0.0.1:8000/v1/health</pre>
<h3>POST /v1/ask</h3>
<pre>curl -X POST http://127.0.0.1:8000/v1/ask -H "Content-Type: application/json" \\
  -d "{\\"question\\": \\"宿舍几点熄灯\\"}"</pre>
<p>返回 <code>behavior</code> 五档之一：answer / answer_with_caveat / clarify / refuse_noanswer / refuse_boundary。</p>
<h3>POST /v1/feedback</h3>
<pre>curl -X POST http://127.0.0.1:8000/v1/feedback -H "Content-Type: application/json" \\
  -d "{\\"session_id\\":\\"x\\",\\"message_id\\":\\"m1\\",\\"resolved\\":true,\\"score\\":5}"</pre>
"""
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(host='127.0.0.1', port=8000):
    return ThreadingHTTPServer((host, port), Handler)
