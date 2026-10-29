# -*- coding: utf-8 -*-
"""接口冒烟测试：四类行为各打一枪，检查契约是否对得上。"""
import json
import time
import urllib.request

BASE = 'http://127.0.0.1:8000'


def call(path, payload=None, method=None):
    url = BASE + path
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={'Content-Type': 'application/json'},
                                 method=method or ('POST' if data else 'GET'))
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


print('=== 健康检查 ===')
t0 = time.time()
code, h = call('/v1/health')
print('HTTP %d  %.1fs  status=%s model=%s chunks=%s 指纹=%s'
      % (code, time.time() - t0, h['status'], h['model'], h['chunks'], h['index_fingerprint']))

CASES = [
    ('正常作答', '宿舍几点熄灯'),
    ('无答案', '图书馆几点开门？'),
    ('越权（代办）', '帮我报修一下宿舍漏水'),
    ('越权（查个人）', '查一下我的期末成绩'),
    ('澄清', '奖学金'),
    ('同义改写', '挂科了还能补考吗'),
]

for label, q in CASES:
    t0 = time.time()
    code, r = call('/v1/ask', {'question': q})
    cost = (time.time() - t0) * 1000
    cits = r.get('citations') or []
    print('\n--- %s：%s ---' % (label, q))
    print('HTTP %d | behavior=%s | confidence=%.2f | %d ms | 引用 %d 条'
          % (code, r['behavior'], r['confidence'], cost, len(cits)))
    print('answer: %s' % r['answer'][:110].replace('\n', ' '))
    if cits:
        print('citation[0]: %s | %s' % (cits[0]['chunk_id'], cits[0]['source'][:46]))
    if r.get('boundary'):
        print('boundary: %s | %s' % (r['boundary']['category'], r['boundary']['channel']['note'][:40]))
    if r.get('suggestions'):
        print('suggestions: %s' % r['suggestions'][:3])

print('\n=== 反馈 ===')
code, f = call('/v1/feedback', {'session_id': 'smoke', 'message_id': 'm-001',
                                'resolved': True, 'score': 5, 'reason': '冒烟测试'})
print('HTTP %d  %s' % (code, f))

print('\n=== 参数校验 ===')
try:
    call('/v1/ask', {'question': ''})
except urllib.error.HTTPError as e:
    print('空问题 → HTTP %d %s' % (e.code, json.loads(e.read().decode())['code']))
try:
    call('/v1/nope')
except urllib.error.HTTPError as e:
    print('错误路径 → HTTP %d %s' % (e.code, json.loads(e.read().decode())['code']))
