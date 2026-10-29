# -*- coding: utf-8 -*-
"""现场演示：连续问几个问题，把系统真实返回打印出来。"""
import json
import urllib.request

BASE = 'http://127.0.0.1:8000/v1/ask'

QUESTIONS = [
    '宿舍几点熄灯？',
    '学分没修满能拿毕业证吗？',
    '我室友天天半夜打游戏，帮我投诉一下',
    '图书馆几点开门？',
    '食堂几点开饭',
]


def ask(q):
    req = urllib.request.Request(
        BASE, data=json.dumps({'question': q}).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode('utf-8'))


for q in QUESTIONS:
    r = ask(q)
    print('\n' + '=' * 66)
    print('问：%s' % q)
    print('-' * 66)
    print('行为：%-16s 置信度：%.2f   耗时：%d ms' % (r['behavior'], r['confidence'], r['latency_ms']))
    print('答：%s' % r['answer'][:420])
    cits = r.get('citations') or []
    if cits:
        print('（回答已附出处，另有 %d 条候选引用）' % len(cits))
    if r.get('suggestions'):
        print('追问建议：%s' % ' / '.join(r['suggestions']))
