# -*- coding: utf-8 -*-
"""生成层：把检索到的条文交给大模型，组织成一句直接回答问题的话。

设计约束（对应需求文档 FR-11/12/21 与 NFR-02）：
  1. 模型只能依据传给它的条文作答，并且必须说明用了哪几条——引用由模型选，但只能从候选里选。
  2. 模型判断「这些条文答不了」时返回 answerable=false，上层走拒答，不硬答。
  3. 模型输出里出现了条文中没有的数字 → 判为不可信，上层退回「条文原文」路径。
  4. 模型不可用（没配密钥、超时、返回格式不对）→ 上层退回「条文原文」路径，服务不中断。

只用标准库（urllib）调用 OpenAI 兼容的 /chat/completions 接口，
国内几家云端模型（DeepSeek、通义千问、智谱）都提供这个兼容接口，换厂商只改配置。
"""
import json
import re
import urllib.error
import urllib.request

# 预置的服务商。model 名称各家会更新，以服务商控制台为准，可在 config.json 的 llm.model 覆盖。
PROVIDERS = {
    'deepseek': {'base_url': 'https://api.deepseek.com', 'model': 'deepseek-chat'},
    'qwen': {'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'qwen-plus'},
    'zhipu': {'base_url': 'https://open.bigmodel.cn/api/paas/v4', 'model': 'glm-4-flash'},
}

SYSTEM_PROMPT = """你是高校「学生手册」问答助手，服务对象是在校学生和教职工。他们用手机提问，想尽快知道一件事该怎么办、规定是什么。

每次提问会附带几条从手册里检索出来的条文（带编号）。检索并不完美：有的条文和问题无关，也可能全部无关。

怎么回答：
- 只依据给出的条文作答。条文里没有的事实、数字、时间、电话、办理窗口，一概不写，也不要用常识补全。
- 先用一两句话直接回答问题，再补充必要的条件、期限、例外或办理步骤。口语化一点，像一位熟悉规定的学长学姐在解释，不要照抄条文原文，也不要逐条复述。
- 多个要点或步骤时分行写，每行以「1.」「2.」开头；不要使用 Markdown 标记（不要 #、*、加粗）。
- 篇幅以说清楚为准，一般不超过 200 字。
- 条文只能回答一部分时，回答能确定的部分，并说明哪一点手册里没有写。
- 这份手册是 2017 年 9 月版。用户问「现在还是这样吗」这类时效问题时，如实说明这是 2017 年版的规定，现行规定以学校最新文件为准。

什么时候不回答：
- 给出的条文都答不了这个问题时，把 answerable 设为 false，不要勉强拼凑答案。
- 用户要求代办、查询个人成绩等个人数据时，同样设为 false。

输出一个 JSON 对象，不要输出别的内容：
{"answerable": true 或 false,
 "answer": "给用户看的回答；answerable 为 false 时留空字符串",
 "cited": ["实际用到的条文编号，如 hb-510；只能从给出的编号里选"],
 "followups": ["用户接下来可能想问的问题，0 到 3 个，必须是给出的条文能回答的"]}"""


class LLMError(Exception):
    """生成层不可用或输出不可信。上层捕获后走降级路径。"""


def settings(cfg):
    """合并「预置服务商 + config.json + 密钥」。返回 None 表示没有启用生成。"""
    spec = dict(cfg.get('llm') or {})
    if not spec.get('enabled', True):
        return None
    preset = PROVIDERS.get(spec.get('provider') or '', {})
    base_url = (spec.get('base_url') or preset.get('base_url') or '').rstrip('/')
    model = spec.get('model') or preset.get('model') or ''
    api_key = (cfg.secret('llm_api_key') or '').strip()
    if not (base_url and model and api_key):
        return None
    return {'base_url': base_url, 'model': model, 'api_key': api_key,
            'timeout': float(spec.get('timeout_seconds', 20)),
            'max_tokens': int(spec.get('max_tokens', 700)),
            'temperature': float(spec.get('temperature', 0.2)),
            'json_mode': bool(spec.get('json_mode', True)),
            'provider': spec.get('provider') or 'custom'}


def status(cfg):
    s = settings(cfg)
    if not s:
        return {'enabled': False, 'provider': '', 'model': ''}
    return {'enabled': True, 'provider': s['provider'], 'model': s['model']}


def _post(s, payload):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        s['base_url'] + '/chat/completions', data=body, method='POST',
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + s['api_key']})
    try:
        with urllib.request.urlopen(req, timeout=s['timeout']) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:200]
        raise LLMError('模型接口返回 HTTP %d：%s' % (e.code, detail))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LLMError('模型接口不可用：%s' % str(e)[:120])


def chat(s, messages):
    payload = {'model': s['model'], 'messages': messages,
               'temperature': s['temperature'], 'max_tokens': s['max_tokens'], 'stream': False}
    if s['json_mode']:
        payload['response_format'] = {'type': 'json_object'}
    try:
        data = _post(s, payload)
    except LLMError as e:
        # 个别服务商/模型不支持 response_format：去掉后重试一次，靠提示词约束输出 JSON
        if not (s['json_mode'] and 'HTTP 400' in str(e)):
            raise
        payload.pop('response_format', None)
        data = _post(s, payload)
    try:
        return data['choices'][0]['message']['content'] or ''
    except (KeyError, IndexError, TypeError):
        raise LLMError('模型返回结构异常')


def _parse(text):
    """模型偶尔会在 JSON 外面包一层 ```json 或多写一句话，取第一个完整的大括号对象。"""
    text = (text or '').strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        raise LLMError('模型没有返回 JSON')
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        raise LLMError('模型返回的 JSON 无法解析')


_NUM = re.compile(r'\d+(?:[.:：]\d+)?')
_LIST_MARK = re.compile(r'(?m)^\s*\d+[.、．)）]\s*')
_HB_ID = re.compile(r'hb-\d+')


_CN_DIGIT = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
             '六': 6, '七': 7, '八': 8, '九': 9}
_CN_UNIT = {'十': 10, '百': 100, '千': 1000}
_CN_RUN = re.compile('[零〇一二两三四五六七八九十百千]+')


def _cn_to_int(run):
    """「三十」→30、「一百二十」→120、「两」→2。只处理万以内，够覆盖条文里的期限和分数。"""
    total = num = 0
    for ch in run:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        else:
            total += (num or 1) * _CN_UNIT[ch]
            num = 0
    return total + num


def _known_numbers(text):
    """原文里出现过的数字：阿拉伯数字按整段取（「22:50」是一个，不拆成 22 和 50），
    中文数字换算成阿拉伯数字——手册写「两周」「三十日」，模型常改写成「2 周」「30 日」。"""
    plain = (text or '').replace('：', ':')
    known = set(_NUM.findall(plain))
    known.update(str(_cn_to_int(run)) for run in _CN_RUN.findall(plain))
    return known


def unsupported_numbers(answer, passages_text, question=''):
    """回答里出现、但条文和问题里都没有的数字。

    数字（期限、分数、金额、时间）是制度问答里最不能错的东西，也是模型最容易编的东西。
    行首的列表序号「1.」「2.」和条文编号不算。
    """
    body = _HB_ID.sub('', _LIST_MARK.sub('', answer or '')).replace('：', ':')
    known = _known_numbers((passages_text or '') + ' ' + (question or ''))
    missing = []
    for token in _NUM.findall(body):
        if token in known:
            continue
        # 「23:30」对应原文「23 时 30 分」：拆开后每一段都有依据也算
        parts = re.split(r'[.:]', token)
        if len(parts) > 1 and all(part in known for part in parts):
            continue
        missing.append(token)
    return missing


def build_messages(question, passages, previous_question=''):
    lines = []
    for p in passages:
        lines.append('【%s】%s\n%s' % (p['id'], p['source'], p['text']))
    user = '检索到的条文：\n\n%s\n\n' % '\n\n'.join(lines)
    if previous_question:
        user += '上一轮用户问的是：%s\n' % previous_question
    user += '用户现在的问题：%s' % question
    return [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': user}]


def generate(cfg, question, passages, previous_question=''):
    """返回 {'answerable', 'answer', 'cited', 'followups', 'model'}；失败抛 LLMError。

    passages: [{'id', 'source', 'text'}]，顺序即检索名次。
    """
    s = settings(cfg)
    if not s:
        raise LLMError('未配置生成模型')
    if not passages:
        raise LLMError('没有可用的条文')
    raw = chat(s, build_messages(question, passages, previous_question))
    data = _parse(raw)
    if not isinstance(data, dict):
        raise LLMError('模型返回的不是 JSON 对象')

    answerable = bool(data.get('answerable'))
    answer = str(data.get('answer') or '').strip()
    known = [p['id'] for p in passages]
    cited = [c for c in (data.get('cited') or []) if isinstance(c, str) and c in known]
    cited = list(dict.fromkeys(cited))
    followups = [str(f).strip() for f in (data.get('followups') or []) if str(f).strip()][:3]

    if not answerable:
        return {'answerable': False, 'answer': '', 'cited': [], 'followups': [], 'model': s['model']}
    if not answer:
        raise LLMError('模型标记可回答但没有给出回答')
    if not cited:
        # 没说依据哪一条的回答不能用：引用是「每句话有出处」的唯一保证
        raise LLMError('模型没有给出有效引用')
    text = ' '.join(p['text'] + ' ' + p['source'] for p in passages if p['id'] in cited)
    missing = unsupported_numbers(answer, text, question)
    if missing:
        raise LLMError('回答含条文中没有的数字：%s' % '、'.join(missing[:5]))
    return {'answerable': True, 'answer': answer, 'cited': cited, 'followups': followups,
            'model': s['model']}
