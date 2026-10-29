# -*- coding: utf-8 -*-
"""回答策略：决定「答 / 澄清 / 拒答 / 拒绝越界」，并拼装带出处的答案。

这一层刻意不接大模型：先用条文原文 + 出处拼装，保证每一句都有依据。
接 7B 之后，这一层仍然是兜底路径（NFR-02 要求模型不可用时降级）。

三条规则的依据：
  FR-11 置信度三档 → 高分直接答、中分澄清、低分拒答
  FR-12 无答案检测 → 低于阈值必须明确拒答，不编造
  FR-20 答复边界   → 代办理/查个人数据/投诉转办一律不接，只给途径
"""
import math
import re

from . import deps, session

# 越界请求：代办理、查个人数据、投诉转办、催办（FR-20 / FR-03）
BOUNDARY_RULES = [
    ('authorized_required', re.compile(
        r'(查|看|报|告诉我).{0,14}(我的|本人|我).{0,8}(成绩|排名|课表|绩点|学分|余额|处分|助学金|奖学金|学费|宿舍|课|单)')),
    ('personal_data', re.compile(r'(我的|本人)(成绩|排名|课表|绩点|学号|身份证|证件号|手机号|家庭住址)')),
    ('complaint', re.compile(r'(帮我|帮忙|替我).{0,4}(投诉|举报|反映)|(投诉|举报|反映).{0,8}(处理|解决|一下|给个说法)|(转给|转交|转办).{0,6}(后勤|学生处|学院|教务处)')),
    ('offline_required', re.compile(r'(帮我|替我|代我).{0,8}(报修|提交|办理|申请|请假|选课|催|撤销|取消|催办)')),
    ('offline_required', re.compile(r'(催|催一下|催办).{0,6}(助学金|奖学金|报销|审批|进度)')),
]

# 只给话题词、信息量不足时先澄清
TOPIC_WORDS = ('宿舍', '奖学金', '医保', '成绩', '转专业', '处分', '毕业', '学分',
               '申诉', '休学', '选课', '勤工助学', '困难生', '住宿', '火车票', '社团')

# 纯疑问套话：「怎么办？」「是什么？」这种什么都没说
VAGUE_RE = re.compile(r'^(怎么办|怎么回事|啥|什么|怎么|如何|能办吗|可以吗|帮我看看|'
                      r'你好|在吗|有人吗|问一下|请问)[\?？。！!]*$')

# 时效/版本类问题：作答必须带「以现行文件为准」的提示（评测集 conflict 三题）
CAVEAT_RE = re.compile(r'(现在还是|现在是否|仍然|还有效|有效吗|2017|版手册|手册写|手册说|'
                       r'不一致|以哪个为准|听谁的|冲突|过期|还适用)')
CAVEAT_TEXT = ('\n\n注意：以上是《学生手册》（2017 年 9 月版）的表述。手册前言写明'
               '「本手册内容与学校文件不符的，以学校文件为准」，若学校已发布或修订相关文件，'
               '请以现行文件为准。')

BOUNDARY_MESSAGES = {
    'offline_required': '这里只提供制度和流程说明，不代为受理、不派发工单、不承诺办理结果。'
                        '具体办理请通过学校公布的官方渠道。',
    'authorized_required': '这里不查询个人业务数据。你的个人事项请通过学校官方系统查询。',
    'personal_data': '为保护隐私，这里不收集、不查询个人证件号、学号等敏感信息。',
    'complaint': '这里不受理投诉建议、不转办诉求、不跟踪处理结果。'
                 '请通过学校公布的投诉渠道反映，并保留受理编号自行查询。',
}

CHANNEL_NOTE = '手册未收录具体办理窗口与电话，请以学校官网/所属部门公布的信息为准。'

_QA_CACHE = {'entries': None}


def _qa_entries():
    """已审核的问答条目（30 条）——用作「推荐问法」的来源，比拼条款名更像人话。"""
    if _QA_CACHE['entries'] is None:
        import json
        import os
        from .config import KB_DIR
        path = os.path.join(KB_DIR, 'data', 'handbook_qa.json')
        try:
            with open(path, encoding='utf-8') as f:
                _QA_CACHE['entries'] = json.load(f)['entries']
        except (OSError, KeyError, ValueError):
            _QA_CACHE['entries'] = []
    return _QA_CACHE['entries']


def _suggestions(question, n=3):
    scored = []
    for e in _qa_entries():
        score = sum(1 for w in set(question) if w in e['title'] + ''.join(e['aliases']))
        if score:
            scored.append((score, e['title']))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:n]]


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, float(x)))))


def _boundary_of(question):
    for category, pattern in BOUNDARY_RULES:
        if pattern.search(question):
            return category
    return None


def _topic_only(question):
    """判断是否「只给了话题词」。

    不能用「字数少」当判据：「宿舍几点熄灯」只有 6 个字，但信息充分；
    「宿舍」「宿舍怎么办」才是真的缺槽位。所以规则是——去掉话题词和疑问套话后
    什么都不剩，才算需要澄清。
    """
    q = re.sub(r'[\s，。！？、,.!?：:；;]', '', question)
    for word in TOPIC_WORDS:
        if word in q:
            rest = q.replace(word, '')
            if rest in ('', '怎么办', '怎么', '如何', '是什么', '有哪些', '呢', '吗',
                        '相关', '规定', '的'):
                return word
    return None


def _citation(chunk, version=1):
    return {
        'chunk_id': chunk.id,
        'doc': chunk.doc,
        'article': chunk.article,
        'page_start': chunk.page_start,
        'page_end': chunk.page_end,
        'source': chunk.source,
        'excerpt': chunk.text[:160],
        'version': version,
        'updated_at': None,
    }


def _history_query(question, req, session_id):
    """多轮：把上一轮问题拼进检索查询，否则「周末也这样吗」单句没有信息。"""
    prev = None
    if req.history:
        prev = req.history[-1].question
    elif session_id:
        prev = session.last_question(session_id)
    if prev and len(question) <= 24:
        return prev + ' ' + question
    return question


def respond(req, cfg=None, retriever=None):
    cfg = cfg or deps.get_config()
    retriever = retriever or deps.get_retriever()
    policy = cfg['answer_policy']
    session_id = req.session_id or session.new_id()
    question = req.question.strip()
    chunks = retriever.chunks

    # ① 边界：先拦，越界问题不进检索
    category = _boundary_of(question)
    if category:
        return {
            'trace_id': _trace(question), 'session_id': session_id,
            'behavior': 'refuse_boundary',
            'answer': BOUNDARY_MESSAGES[category],
            'citations': [], 'confidence': 0.0, 'suggestions': [],
            'boundary': {'category': category, 'message': BOUNDARY_MESSAGES[category],
                         'channel': {'unit': '', 'window': '', 'phone': '',
                                     'service_hours': '', 'url': None,
                                     'url_checked_at': None, 'note': CHANNEL_NOTE}},
            'degraded': False, 'knowledge_version': cfg.kb['corpus']['version'],
            'latency_ms': 0,
        }

    # ② 澄清：只有话题词
    # ② 只给话题词 → 澄清；纯疑问套话（「怎么办？」）也走这条
    topic = _topic_only(question)
    if topic or VAGUE_RE.match(question.strip()):
        options = _suggestions(question, policy['max_suggestions'])
        text = ('你想了解「%s」的哪方面？可以补充具体事项，或从下面的问题里选一个。' % topic
                if topic else '能再说具体一点吗？比如你要办什么事、遇到的什么情况。')
        return {
            'trace_id': _trace(question), 'session_id': session_id,
            'behavior': 'clarify',
            'answer': text,
            'citations': [], 'confidence': 0.3,
            'suggestions': options,
            'boundary': None, 'degraded': False,
            'knowledge_version': cfg.kb['corpus']['version'], 'latency_ms': 0,
        }

    # ③ 检索
    query = _history_query(question, req, req.session_id)
    hits = retriever.search(query, k=cfg.kb['retrieval']['top_k'])
    if not hits:
        return _refuse(question, session_id, cfg, retriever)

    top_id, top_score = hits[0]
    confidence = _sigmoid(top_score)
    second = _sigmoid(hits[1][1]) if len(hits) > 1 else 0.0

    # ④ 低置信 → 拒答（FR-12）
    if confidence < policy['refuse_below']:
        return _refuse(question, session_id, cfg, retriever, confidence)

    # ⑤ 中置信 → 澄清（FR-11 中间档）
    # 注意：不再用「前两名分数太接近」作判据。rerank logit 经 sigmoid 后在 0.9 以上
    # 会饱和，两条都在 0.99 时差值恒为 0.001 级，会把高置信的正确回答误判成歧义
    # （实测「学分没修满能拿毕业证吗」置信度 0.95 却被澄清）。歧义由 ② 的话题词规则承担。
    if confidence < policy['clarify_below']:
        top = chunks[top_id]
        return {
            'trace_id': _trace(question), 'session_id': session_id,
            'behavior': 'clarify',
            'answer': '我不太确定你指的是哪一项。是不是想问：%s？' % _title(top),
            'citations': [_citation(top)], 'confidence': round(confidence, 3),
            'suggestions': _suggestions(question, policy['max_suggestions']),
            'boundary': None, 'degraded': False,
            'knowledge_version': cfg.kb['corpus']['version'], 'latency_ms': 0,
        }

    # ⑥ 正常作答：条文原文 + 出处；时效类问题追加「以现行文件为准」
    top = chunks[top_id]
    answer = '%s\n\n出处：%s' % (top.text, top.source)
    behavior = 'answer'
    if CAVEAT_RE.search(question):
        answer += CAVEAT_TEXT
        behavior = 'answer_with_caveat'
    return {
        'trace_id': _trace(question), 'session_id': session_id,
        'behavior': behavior, 'answer': answer,
        'citations': [_citation(c) for c, _ in ((chunks[cid], s) for cid, s in hits)],
        'confidence': round(confidence, 3),
        'suggestions': _suggestions(question, policy['max_suggestions']),
        'boundary': None, 'degraded': False,
        'knowledge_version': cfg.kb['corpus']['version'], 'latency_ms': 0,
    }


def _title(chunk):
    return '%s%s' % (chunk.article or '', '（第%d页）' % chunk.page_start)


def _refuse(question, session_id, cfg, retriever, confidence=0.0):
    """无答案：明确说查不到，并给出「去哪儿问」，不编造任何事实。"""
    return {
        'trace_id': _trace(question), 'session_id': session_id,
        'behavior': 'refuse_noanswer',
        'answer': '当前知识库（学生手册 2017 年版）里没有足够可靠的依据回答这个问题，'
                  '我不做推测。建议你确认具体事项，或通过学校官网/所属部门公布的渠道核实。',
        'citations': [], 'confidence': round(confidence, 3), 'suggestions': [],
        'boundary': {'category': 'offline_required',
                     'message': '本系统只提供已审核知识的查询，无法回答知识库外的问题。',
                     'channel': {'unit': '', 'window': '', 'phone': '', 'service_hours': '',
                                 'url': None, 'url_checked_at': None, 'note': CHANNEL_NOTE}},
        'degraded': False, 'knowledge_version': cfg.kb['corpus']['version'], 'latency_ms': 0,
    }


def _trace(question):
    import hashlib
    return hashlib.sha1(('%s|%f' % (question, __import__('time').time())).encode()).hexdigest()[:12]
