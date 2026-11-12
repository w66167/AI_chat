# -*- coding: utf-8 -*-
"""生成层、登录与身份、手册浏览、HTTP 接口的测试。

特点：不需要显卡、不需要模型权重、不联网——
  检索用关键词保底路径（标准库），大模型用假的生成函数或本机假接口顶替，微信接口不调用。

跑法（在仓库根目录）：
    python backend/tests/test_service.py
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# 测试不能受本机密钥影响：先清掉环境变量，再把 secrets 置空
for name in ('CAMPUS_LLM_API_KEY', 'CAMPUS_WECHAT_APPID', 'CAMPUS_WECHAT_SECRET', 'CAMPUS_TEACHER_CODE'):
    os.environ.pop(name, None)

from app import answer, auth, deps, handbook, history, libraries, llm   # noqa: E402
from app.schemas import AskRequest                                       # noqa: E402
from app.server import make_server                                       # noqa: E402

TMP = tempfile.mkdtemp(prefix='campus-test-')
auth.reset_for_tests(os.path.join(TMP, 'users.json'), os.path.join(TMP, 'token.key'))
history.reset_for_tests(os.path.join(TMP, 'history.json'))

CFG = deps.get_config()
CFG.secrets = {}
CFG.data['search'] = {'backend': 'lexical'}      # 测试固定走关键词检索，不碰显卡

DORM = 'hb-510'
LAW_APPEAL = '对学校的处分不服可以申诉吗？'


def ask(question, identity='student', generate=False, history_turns=None):
    req = AskRequest(question=question, session_id='t', history=history_turns or [])
    return answer.respond(req, cfg=CFG, identity=identity, generate=generate)


# ---------------------------------------------------------------- 检索保底路径

def test_lexical_retriever_answers_without_models():
    """没有向量模型时也要能答：关键词检索 + 条文原文。"""
    resp = ask('宿舍几点熄灯')
    assert resp['behavior'] == 'answer', resp['behavior']
    assert resp['citations'][0]['chunk_id'] == DORM
    assert resp['answer_mode'] == 'excerpt'
    assert deps.status()['mode'] == 'lexical'


def accepting(seen=None):
    """假的生成函数：引用排第一的条文并原样作答。用来测「有大模型把关」时的检索与门槛。"""
    def run(cfg, question, passages, previous=''):
        if seen is not None:
            seen.update(passages=passages)
        return {'answerable': True, 'answer': '依据条文作答。', 'cited': [passages[0]['id']],
                'followups': [], 'model': 'fake'}
    return run


def test_colloquial_question_reaches_the_model():
    """「挂科」不在条文里，靠问答条目的问法字段把补考规定排进候选，交给模型判断。"""
    seen = {}
    resp = ask('挂科了还能补考吗', generate=accepting(seen))
    assert resp['behavior'] == 'answer'
    assert 'hb-142' in [p['id'] for p in seen['passages']]


def test_threshold_is_stricter_without_a_model():
    """关键词检索分不清「相关条文」和「碰巧同字的条文」。
    有模型把关时门槛低（让模型判断答不答得了）；直接给条文原文时门槛高（宁可少答）。"""
    weak = '挂科了还能补考吗'                     # 关键词得分低的口语短问法
    assert ask(weak)['behavior'] == 'refuse_noanswer'
    assert ask(weak, generate=accepting())['behavior'] == 'answer'
    # 手册里没有、但字面上沾边的问题：没有模型时必须拒掉
    for q in ('校园卡丢了怎么挂失？', '我们专业一年学费多少钱？', '校园网密码忘了怎么办？'):
        assert ask(q)['behavior'] == 'refuse_noanswer', q
    # 界面上给出的示例问题，在最差的组合下（关键词检索 + 条文原文）也都要答得出来
    for group in handbook.suggestions('student')['groups']:
        for q in group['questions']:
            assert ask(q)['behavior'] in ('answer', 'answer_with_caveat'), q


def test_lexical_refuses_out_of_scope():
    for q in ('月球上可以种什么花', '食堂今天有什么菜'):
        assert ask(q)['behavior'] == 'refuse_noanswer', q


def test_boundary_and_clarify_still_apply():
    assert ask('帮我报修一下宿舍漏水')['behavior'] == 'refuse_boundary'
    assert ask('奖学金')['behavior'] == 'clarify'


# ---------------------------------------------------------------- 生成层

def fake_generate(result=None, error=None, seen=None):
    def run(cfg, question, passages, previous=''):
        if seen is not None:
            seen.update(question=question, passages=passages, previous=previous)
        if error:
            raise llm.LLMError(error)
        return result
    return run


def test_generated_answer_replaces_excerpt():
    seen = {}
    gen = fake_generate({'answerable': True, 'answer': '周日到周四 22:50 自主熄灯。', 'cited': [DORM],
                         'followups': ['晚归了怎么办？'], 'model': 'fake'}, seen=seen)
    resp = ask('宿舍几点熄灯', generate=gen)
    assert resp['answer_mode'] == 'generated' and resp['model'] == 'fake'
    assert resp['answer'] == '周日到周四 22:50 自主熄灯。'
    # 引用只留模型实际用到的那条；候选给了 5 条（比展示的前 3 名多，召回更高）
    assert [c['chunk_id'] for c in resp['citations']] == [DORM]
    assert len(seen['passages']) == 5 and seen['passages'][0]['id'] == DORM
    assert resp['suggestions'] == ['晚归了怎么办？']
    assert resp['degraded'] is False


def test_model_can_decline():
    """模型判断条文答不了 → 拒答，而不是把不相关的条文原文贴出来。"""
    resp = ask('宿舍几点熄灯', generate=fake_generate({'answerable': False, 'answer': '', 'cited': [],
                                                    'followups': [], 'model': 'fake'}))
    assert resp['behavior'] == 'refuse_noanswer'
    assert resp['citations'] == []


def test_generation_failure_degrades_to_excerpt():
    resp = ask('宿舍几点熄灯', generate=fake_generate(error='模型接口不可用：timeout'))
    assert resp['behavior'] == 'answer'
    assert resp['answer_mode'] == 'excerpt' and resp['degraded'] is True
    assert resp['citations'][0]['chunk_id'] == DORM
    assert deps.llm_errors()['last_error'].startswith('模型接口不可用')


def test_followup_passes_previous_question_to_model():
    seen = {}
    gen = fake_generate({'answerable': True, 'answer': '晚归要登记。', 'cited': [DORM],
                         'followups': [], 'model': 'fake'}, seen=seen)
    ask('晚归了怎么办', generate=gen, history_turns=[{'question': '宿舍几点熄灯'}])
    assert seen['previous'] == '宿舍几点熄灯'


def test_generation_never_runs_for_guest_on_restricted_content():
    """游客问校内规章：范围内没有可答的条文就拒答，受限条文不会被送进模型。"""
    seen = {}
    gen = fake_generate({'answerable': False, 'answer': '', 'cited': [], 'followups': [], 'model': 'f'}, seen=seen)
    ask('宿舍几点熄灯', identity='guest', generate=gen)
    for p in seen.get('passages', []):
        assert libraries.kb_of_chunk(p['id']) == 'public-guide', p['id']


def test_unsupported_numbers():
    src = '本科生周日至周四自主熄灯22:50、统一熄灯23:30。请假期限不得超过两周。2017年9月。'
    assert llm.unsupported_numbers('22:50 自主熄灯，23：30 统一熄灯。', src) == []
    assert llm.unsupported_numbers('1. 先申请\n2. 再审批', src) == []            # 列表序号不算
    assert llm.unsupported_numbers('最晚 23:00 熄灯', src) == ['23:00']
    assert llm.unsupported_numbers('需缴纳 50 元', src) == ['50']
    assert llm.unsupported_numbers('依据 hb-510', src) == []                       # 条文编号不算
    assert llm.unsupported_numbers('3 天内办理', src, question='3 天内能办完吗') == []   # 问题里有的不算编造
    # 手册多用中文数字：「两周」写成「2 周」、「三十日」写成「30 日」不算编造，写错了才算
    assert llm.unsupported_numbers('请假不超过 2 周', src) == []
    assert llm.unsupported_numbers('应在 30 日内提出', '应当在三十日内提出；一百二十学分') == []
    assert llm.unsupported_numbers('修满 120 学分', '应当在三十日内提出；一百二十学分') == []
    assert llm.unsupported_numbers('应在 15 日内提出', '应当在三十日内提出') == ['15']
    # 「22:50」是一个整体，不能因此认为单独的 50 有依据
    assert llm.unsupported_numbers('罚款 50 元', '自主熄灯22:50') == ['50']


class FakeLLM(BaseHTTPRequestHandler):
    """本机假的 /chat/completions：按 reply 队列依次回应。"""
    replies, requests = [], []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8'))
        FakeLLM.requests.append({'path': self.path, 'auth': self.headers.get('Authorization'), 'body': body})
        status, content = FakeLLM.replies.pop(0)
        payload = json.dumps({'choices': [{'message': {'content': content}}]} if status == 200
                             else {'error': {'message': content}}, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def with_fake_llm(fn):
    server = ThreadingHTTPServer(('127.0.0.1', 0), FakeLLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    saved_llm, saved_secrets = dict(CFG.data['llm']), dict(CFG.secrets)
    CFG.data['llm'].update({'provider': '', 'base_url': 'http://127.0.0.1:%d/v1' % server.server_port,
                            'model': 'test-model', 'timeout_seconds': 5})
    CFG.secrets = {'llm_api_key': 'sk-test'}
    FakeLLM.replies, FakeLLM.requests = [], []
    try:
        fn()
    finally:
        CFG.data['llm'], CFG.secrets = saved_llm, saved_secrets
        server.shutdown()


PASSAGES = [{'id': DORM, 'source': '《住宿管理规定》第二十二条 第174页',
             'text': '本科生周日至周四自主熄灯22:50、统一熄灯23:30。'},
            {'id': 'hb-511', 'source': '《住宿管理规定》第二十三条 第174页', 'text': '学生应保持寝室整洁。'}]


def test_llm_http_roundtrip():
    def run():
        FakeLLM.replies.append((200, json.dumps({'answerable': True, 'answer': '22:50 自主熄灯，23:30 统一熄灯。',
                                                'cited': [DORM, 'hb-999'], 'followups': ['a', 'b', 'c', 'd']},
                                               ensure_ascii=False)))
        out = llm.generate(CFG, '宿舍几点熄灯', PASSAGES)
        assert out['answerable'] and out['model'] == 'test-model'
        assert out['cited'] == [DORM]                 # 候选之外的编号被丢掉
        assert len(out['followups']) == 3
        sent = FakeLLM.requests[0]
        assert sent['path'] == '/v1/chat/completions' and sent['auth'] == 'Bearer sk-test'
        assert sent['body']['response_format'] == {'type': 'json_object'}
        assert DORM in sent['body']['messages'][1]['content']
    with_fake_llm(run)


def test_llm_rejects_bad_outputs():
    def run():
        cases = [
            ('编造数字', json.dumps({'answerable': True, 'answer': '23:00 熄灯', 'cited': [DORM]}), '没有的数字'),
            ('没有引用', json.dumps({'answerable': True, 'answer': '按时熄灯', 'cited': []}), '有效引用'),
            ('不是 JSON', '我认为应该按时熄灯', '没有返回 JSON'),
            ('空回答', json.dumps({'answerable': True, 'answer': '', 'cited': [DORM]}), '没有给出回答'),
        ]
        for label, reply, expect in cases:
            FakeLLM.replies.append((200, reply))
            try:
                llm.generate(CFG, '宿舍几点熄灯', PASSAGES)
            except llm.LLMError as e:
                assert expect in str(e), (label, str(e))
            else:
                raise AssertionError('应当拒绝：%s' % label)
        # 包在 ```json 里的也要能解析
        FakeLLM.replies.append((200, '```json\n%s\n```' % json.dumps({'answerable': False})))
        assert llm.generate(CFG, '宿舍几点熄灯', PASSAGES)['answerable'] is False
    with_fake_llm(run)


def test_llm_retries_without_json_mode_and_reports_http_errors():
    def run():
        FakeLLM.replies += [(400, 'response_format not supported'),
                            (200, json.dumps({'answerable': True, 'answer': '按时熄灯', 'cited': [DORM]}))]
        assert llm.generate(CFG, '宿舍几点熄灯', PASSAGES)['answer'] == '按时熄灯'
        assert 'response_format' not in FakeLLM.requests[1]['body']
        FakeLLM.replies.append((401, 'invalid api key'))
        try:
            llm.generate(CFG, '宿舍几点熄灯', PASSAGES)
        except llm.LLMError as e:
            assert 'HTTP 401' in str(e)
        else:
            raise AssertionError('密钥错误应当报错')
    with_fake_llm(run)


def test_llm_disabled_without_key():
    assert llm.settings(CFG) is None
    assert llm.status(CFG) == {'enabled': False, 'provider': '', 'model': ''}


# ---------------------------------------------------------------- 登录与身份

def test_dev_login_and_token():
    assert auth.mode(CFG) == 'dev'
    a = auth.login(CFG, device_id='device-aaaa-1111')
    again = auth.login(CFG, device_id='device-aaaa-1111')
    other = auth.login(CFG, device_id='device-bbbb-2222')
    assert a['user']['id'] == again['user']['id'] != other['user']['id']
    assert a['user']['identity_type'] == 'guest'
    assert auth.verify_token(a['token'])['id'] == a['user']['id']
    # 改过的、过期的、乱写的令牌一律无效
    assert auth.verify_token(a['token'][:-1] + ('0' if a['token'][-1] != '0' else '1')) is None
    assert auth.verify_token(auth.issue_token(a['user']['id'], -10)) is None
    assert auth.verify_token('abc') is None and auth.verify_token('') is None
    for bad in ('', 'short'):
        try:
            auth.login(CFG, device_id=bad)
        except auth.AuthError as e:
            assert e.code == 'DEVICE_REQUIRED'
        else:
            raise AssertionError('设备号不合规应当拒绝')


def test_bind_identity_and_teacher_code():
    user = auth.login(CFG, device_id='device-cccc-3333')['user']
    assert auth.bind_identity(CFG, user['id'], 'student')['identity_type'] == 'student'
    assert auth.get_user(user['id'])['verified'] is False       # 自行声明不等于已核验
    try:
        auth.bind_identity(CFG, user['id'], 'staff')            # 管理端身份不能在用户端绑定
    except auth.AuthError as e:
        assert e.code == 'BAD_IDENTITY'
    else:
        raise AssertionError('不应允许绑定管理端身份')
    CFG.secrets = {'teacher_code': 'T-2026'}
    try:
        assert auth.binding_rules(CFG)['teacher'] == 'code'
        try:
            auth.bind_identity(CFG, user['id'], 'teacher', 'wrong')
        except auth.AuthError as e:
            assert e.code == 'BAD_CODE' and e.status == 403
        else:
            raise AssertionError('口令错误应当拒绝')
        assert auth.get_user(user['id'])['identity_type'] == 'student'
        assert auth.bind_identity(CFG, user['id'], 'teacher', 'T-2026')['identity_type'] == 'teacher'
    finally:
        CFG.secrets = {}
    assert auth.bind_identity(CFG, user['id'], 'guest')['bound_at'] == ''


def test_wechat_mode_requires_code():
    CFG.secrets = {'wechat_appid': 'wx123', 'wechat_secret': 's'}
    try:
        assert auth.mode(CFG) == 'wechat'
        try:
            auth.login(CFG, device_id='device-aaaa-1111')       # 配了微信就不再接受设备号登录
        except auth.AuthError as e:
            assert e.code == 'CODE_REQUIRED'
        else:
            raise AssertionError('微信模式下不应接受设备号')
    finally:
        CFG.secrets = {}


# ---------------------------------------------------------------- 手册浏览

def test_catalog_by_identity():
    guest, student = handbook.catalog('guest'), handbook.catalog('student')
    assert (guest['visible'], guest['hidden'], guest['total']) == (3, 25, 28)
    assert [g['category'] for g in guest['groups']] == ['国家法规']
    assert (student['visible'], student['hidden']) == (28, 0)
    assert len(student['groups']) == 7
    indexes = sorted(d['index'] for g in student['groups'] for d in g['docs'])
    assert indexes == list(range(1, 29)), '28 份文件每份都要归到某个分类'


def test_document_and_article_respect_identity():
    assert handbook.document('guest', 26) is None            # 住宿规定：游客不可见
    assert handbook.document('guest', 999) is None           # 不存在的文件：同样的回答
    doc = handbook.document('student', 26)
    assert doc['doc']['name'] == '杭州电子科技大学学生住宿管理规定'
    assert sum(len(c['articles']) for c in doc['chapters']) == 52
    assert handbook.document('guest', 1)['doc']['kb_id'] == 'public-guide'

    assert handbook.article('guest', DORM) is None
    art = handbook.article('student', DORM)
    assert art['article'] == '第二十二条' and art['page_start'] == 174
    assert art['kb']['id'] == 'student-handbook' and '熄灯' in art['text']
    assert art['prev']['id'] == 'hb-509' and art['next']['id'] == 'hb-511'
    assert handbook.article('student', 'hb-999') is None
    # 一份文件的第一条没有「上一条」，不会翻到别的文件里去
    first = handbook.article('student', doc['chapters'][0]['articles'][0]['id'])
    assert first['prev'] is None


def test_search_respects_identity():
    hits = handbook.search('student', '熄灯')
    assert hits and hits[0]['id'] == DORM and '熄灯' in hits[0]['snippet']
    assert handbook.search('guest', '熄灯') == []
    assert all(libraries.kb_of_chunk(h['id']) == 'public-guide' for h in handbook.search('guest', '申诉'))
    assert handbook.search('student', '') == []


def test_suggestions_by_identity():
    guest, student = handbook.suggestions('guest'), handbook.suggestions('student')
    assert LAW_APPEAL in guest['questions'] and guest['groups'] == []
    assert len(student['questions']) == 8 and len(student['groups']) == 7
    assert sum(len(g['questions']) for g in student['groups']) == 30
    # 给游客的示例问题必须真的能在游客范围内答出来（最差的组合下也要能）
    for q in guest['questions']:
        resp = ask(q, identity='guest')
        assert resp['behavior'] == 'answer', q
        assert all(c['kb']['id'] == 'public-guide' for c in resp['citations']), q


# ---------------------------------------------------------------- HTTP 接口

class Client:
    def __init__(self, port):
        self.base, self.token = 'http://127.0.0.1:%d' % port, ''

    def call(self, path, payload=None):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers,
                                     method='POST' if data is not None else 'GET')
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8'))


def test_http_end_to_end():
    server = make_server('127.0.0.1', 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    c = Client(server.server_port)
    try:
        code, h = c.call('/v1/health')
        assert code == 200 and h['retrieval'] == 'lexical' and h['auth_mode'] == 'dev'
        assert h['llm']['enabled'] is False

        # 没登录 = 游客。请求体里自称 teacher 不起作用（以前这样能越权）
        code, r = c.call('/v1/ask', {'question': '宿舍几点熄灯', 'scope': {'identity_type': 'teacher'}})
        assert code == 200 and r['identity_type'] == 'guest' and r['behavior'] == 'refuse_noanswer'
        assert c.call('/v1/handbook/article?id=' + DORM)[0] == 404
        assert c.call('/v1/me')[0] == 401 and c.call('/v1/history')[0] == 401

        code, login = c.call('/v1/auth/login', {'device_id': 'http-device-0001'})
        assert code == 200 and login['identity_type'] == 'guest'
        c.token = login['token']
        assert [lib['id'] for lib in login['libraries'] if lib['accessible']] == ['public-guide']
        assert c.call('/v1/history')[0] == 403               # 游客不保存提问记录
        code, r = c.call('/v1/ask', {'question': LAW_APPEAL})
        assert r['behavior'] == 'answer' and r['citations'][0]['kb']['id'] == 'public-guide'

        code, me = c.call('/v1/me/identity', {'identity_type': 'student'})
        assert code == 200 and me['identity_type'] == 'student'
        assert [lib['id'] for lib in me['libraries'] if lib['accessible']] == ['public-guide', 'student-handbook']
        assert c.call('/v1/me/identity', {'identity_type': 'staff'})[0] == 400

        code, r = c.call('/v1/ask', {'question': '宿舍几点熄灯'})
        assert r['identity_type'] == 'student' and r['citations'][0]['chunk_id'] == DORM
        code, art = c.call('/v1/handbook/article?id=' + r['citations'][0]['chunk_id'])
        assert code == 200 and art['article'] == '第二十二条'  # 回答里的引用都能点进原文
        assert c.call('/v1/handbook/catalog')[1]['visible'] == 28
        assert c.call('/v1/handbook/doc?index=26')[1]['doc']['chunks'] == 52
        assert c.call('/v1/handbook/search?q=%E7%86%84%E7%81%AF')[1]['items'][0]['id'] == DORM
        assert len(c.call('/v1/suggestions')[1]['questions']) == 8

        code, hist = c.call('/v1/history')
        assert code == 200 and [i['question'] for i in hist['items']] == ['宿舍几点熄灯']
        assert c.call('/v1/history/clear', {})[1]['ok'] is True
        assert c.call('/v1/history')[1]['items'] == []

        assert c.call('/v1/feedback', {'session_id': 's', 'message_id': 'm1', 'resolved': True, 'score': 5})[0] == 200
        assert c.call('/v1/ask', {'question': ''})[1]['code'] == 'EMPTY_QUESTION'
        assert c.call('/v1/nope')[1]['code'] == 'NOT_FOUND'
        # 伪造或过期的令牌 → 一律 401（不悄悄降级成游客），客户端据此重新登录
        c.token = 'forged.token.value'
        for path in ('/v1/me', '/v1/handbook/article?id=' + DORM, '/v1/handbook/catalog', '/v1/suggestions'):
            code, body = c.call(path)
            assert code == 401 and body['code'] in ('TOKEN_INVALID', 'UNAUTHORIZED'), (path, code, body)
        assert c.call('/v1/ask', {'question': '宿舍几点熄灯'})[0] == 401
        c.token = ''                                         # 不带令牌才是游客
        assert c.call('/v1/handbook/article?id=' + DORM)[0] == 404
        assert c.call('/v1/handbook/catalog')[1]['visible'] == 3
    finally:
        server.shutdown()


def test_keepalive_connection_survives_unread_bodies():
    """同一条连接上连续发请求：前一个请求的请求体不能污染下一个请求。

    小程序和浏览器都会复用连接。清空记录、鉴权失败、路径不存在这些接口不需要请求体，
    服务端如果不把它读走，下一个请求就会被解析坏（表现为 501）。"""
    import http.client
    server = make_server('127.0.0.1', 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)

    def post(path, payload, token=''):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        conn.request('POST', path, body=json.dumps(payload).encode('utf-8'), headers=headers)
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read().decode('utf-8'))

    try:
        status, login = post('/v1/auth/login', {'device_id': 'keepalive-device-1'})
        token = login['token']
        assert post('/v1/me/identity', {'identity_type': 'student'}, token)[0] == 200
        steps = [
            ('/v1/history/clear', {'ignored': 'x' * 300}, token, 200),   # 接口不用请求体
            ('/v1/me/identity', {'identity_type': 'student'}, '', 401),  # 鉴权失败提前返回
            ('/v1/nope', {'a': 1}, token, 404),                          # 路径不存在
            ('/v1/me/identity', {'identity_type': 'staff'}, token, 400),
            ('/v1/ask', {'question': '宿舍几点熄灯'}, token, 200),
        ]
        for path, payload, tok, expect in steps:
            status, body = post(path, payload, tok)
            assert status == expect, (path, status, body)
        conn.request('POST', '/v1/ask', body=b'not json', headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        assert resp.status == 400 and json.loads(resp.read())['code'] == 'BAD_REQUEST'
        assert post('/v1/ask', {'question': '宿舍几点熄灯'}, token)[0] == 200   # 坏请求之后连接仍可用
    finally:
        conn.close()
        server.shutdown()


def main():
    import app.server as server_module
    server_module.FEEDBACK_LOG = os.path.join(TMP, 'feedback.jsonl')
    tests = [(n, f) for n, f in globals().items() if n.startswith('test_') and callable(f)]
    for name, fn in tests:
        fn()
        print('PASS %s' % name)
    print('全部服务测试通过（%d 项，无需模型、显卡与网络）' % len(tests))


if __name__ == '__main__':
    main()
