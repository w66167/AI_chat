# -*- coding: utf-8 -*-
"""知识库路由与出处标注的离线测试。

特点：**不需要 GPU、不需要加载嵌入/重排模型**。
检索器用 FakeRetriever 顶替，只验证「按身份选库 → 在范围内检索 → 引用带知识库」这条链路。

跑法（在仓库根目录）：
    python backend/tests/test_libraries.py            # 直接运行
    python -m pytest backend/tests/test_libraries.py  # 装了 pytest 也可以
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app import answer, libraries                      # noqa: E402
from app.schemas import AskRequest                     # noqa: E402
from kb.corpus import load_chunks                      # noqa: E402

KB_DIR = os.path.join(ROOT, 'knowledge_base')
CHUNKS_PATH = os.path.join(KB_DIR, 'data', 'handbook_chunks.jsonl')
MINI_LIBRARIES = os.path.join(ROOT, 'campus-assistant', 'miniprogram', 'data', 'libraries.js')


class FakeRetriever:
    """固定返回给定顺序的知识块，分数稳定在「正常作答」档。只验证路由与出处。"""

    def __init__(self, chunks, ids=None, score=3.0):
        self.chunks = {c.id: c for c in chunks}
        self._ids = list(ids) if ids else [c.id for c in chunks]
        self.score = score

    def search(self, query, k=3):
        return [(cid, self.score - i * 0.01) for i, cid in enumerate(self._ids[:k])]


def ask(question, identity, retriever):
    request = AskRequest(question=question, session_id='test-session',
                         scope={'identity_type': identity})
    return answer.respond(request, retriever=retriever)


def load():
    return load_chunks(CHUNKS_PATH)


# ---------------------------------------------------------------- 注册表

def test_registry_matches_miniprogram():
    """后端读的 libraries.json 与小程序 require 的 libraries.js 必须是同一份内容。

    两边不一致会出现「后端检索了学生手册、前端显示公开指南」这种最难的排查项，
    所以这里做一次字面比对。
    """
    with open(MINI_LIBRARIES, encoding='utf-8') as f:
        js = f.read()
    for item in libraries.libraries():
        assert '"id": "%s"' % item['id'] in js, '小程序端缺少知识库 %s' % item['id']
        assert json.dumps(item['audience'], ensure_ascii=False) in js, \
            '知识库 %s 的身份范围没有同步到小程序端' % item['id']
    for item in libraries.registry()['identities']:
        assert '"id": "%s"' % item['id'] in js, '小程序端缺少身份 %s' % item['id']


def test_identity_routing():
    assert [i['id'] for i in libraries.for_identity('guest')] == ['public-guide']
    assert [i['id'] for i in libraries.for_identity('student')] == ['public-guide', 'student-handbook']
    assert [i['id'] for i in libraries.for_identity('teacher')] == \
        ['public-guide', 'student-handbook', 'staff-handbook']
    assert [i['id'] for i in libraries.for_identity('staff')] == \
        ['public-guide', 'student-handbook', 'staff-handbook']
    # 只有学生手册真的建了索引，公开指南与教职工手册都还没有
    assert [i['id'] for i in libraries.searchable_for('student')] == ['student-handbook']
    assert [i['id'] for i in libraries.searchable_for('guest')] == []
    # 公开指南与教职工手册都还没接入检索，要如实列出来
    assert [i['id'] for i in libraries.pending_for('teacher')] == ['public-guide', 'staff-handbook']


def test_chunk_owner():
    """知识块要能反查出所属知识库，否则按身份过滤无从谈起。"""
    chunks = load()
    assert libraries.kb_of_chunk(chunks[0].id) == 'student-handbook'
    assert libraries.kb_of_chunk('hb-not-exist') is None


def test_filter_hits():
    original = libraries._CHUNK_OWNER
    try:
        libraries._CHUNK_OWNER = {'a': 'staff-handbook', 'b': 'student-handbook'}
        hits = [('a', 0.9), ('b', 0.8)]
        assert libraries.filter_hits(hits, ['student-handbook']) == [('b', 0.8)]
        # 注册表一个块都没登记时不静默清空结果——那会变成「什么都查不到」的隐形故障
        libraries._CHUNK_OWNER = {}
        assert libraries.filter_hits(hits, []) == hits
    finally:
        libraries._CHUNK_OWNER = original


# ---------------------------------------------------------------- 回答行为

def test_guest_has_no_searchable_library():
    """游客的知识库（公开指南）还没接入检索：要如实说明，而不是拿学生手册冒充。"""
    resp = ask('宿舍几点熄灯', 'guest', FakeRetriever(load()))
    assert resp['kb_gap'] is True
    assert resp['knowledge_bases'] == []
    assert '公开办事指南' in resp['kb_gap_reason']
    assert resp['behavior'] == 'refuse_noanswer'
    assert resp['citations'] == []


def test_student_answer_carries_library():
    resp = ask('宿舍几点熄灯', 'student', FakeRetriever(load()))
    assert resp['behavior'] in ('answer', 'answer_with_caveat')
    assert resp['knowledge_bases'][0]['id'] == 'student-handbook'
    assert resp['citations'], '正常作答必须带引用'
    citation = resp['citations'][0]
    assert citation['kb']['id'] == 'student-handbook'
    assert citation['kb']['name'] == '学生手册'
    assert citation['kb']['version'] == 'hb-2017-v1'
    # 引用要能定位到具体文件、条号与页码，不能只给一个知识库名字
    assert citation['doc']
    assert citation['source']
    assert citation['page_start'] >= 1


def test_teacher_is_told_about_pending_library():
    """教师还能访问教职工手册，但它没接入检索——必须在答案里声明没查它。"""
    resp = ask('宿舍几点熄灯', 'teacher', FakeRetriever(load()))
    assert resp['kb_pending'] == ['校园公开办事指南', '教职工手册']
    assert '教职工手册' in resp['answer']
    assert '尚未接入检索' in resp['answer']


def test_scope_filter_runs_before_topk():
    """范围外的块不能占名额：前两块属于教职工手册时，学生应该命中第三块（学生手册）。"""
    chunks = load()[:4]
    retriever = FakeRetriever(chunks, ids=[chunks[0].id, chunks[1].id, chunks[2].id])
    original = libraries._CHUNK_OWNER
    try:
        libraries._CHUNK_OWNER = {chunks[0].id: 'staff-handbook',
                                  chunks[1].id: 'staff-handbook',
                                  chunks[2].id: 'student-handbook'}
        resp = ask('任意问题', 'student', retriever)
        assert resp['citations'][0]['chunk_id'] == chunks[2].id
        assert [c['kb']['id'] for c in resp['citations']] == ['student-handbook']
    finally:
        libraries._CHUNK_OWNER = original


def test_refuse_names_the_searched_library():
    """拒答话术要点名实际检索过的知识库，不能笼统说「知识库」。"""
    resp = ask('宿舍几点熄灯', 'student', FakeRetriever(load(), score=-5.0))
    assert resp['behavior'] == 'refuse_noanswer'
    assert '学生手册' in resp['answer']


def main():
    tests = [(name, obj) for name, obj in sorted(globals().items()) if name.startswith('test_') and callable(obj)]
    for name, fn in tests:
        fn()
        print('PASS %s' % name)
    print('全部知识库路由测试通过（%d 项，无需加载模型）' % len(tests))


if __name__ == '__main__':
    main()
