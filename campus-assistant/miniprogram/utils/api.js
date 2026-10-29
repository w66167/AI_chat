// 后端 API 封装。
// 设计要点：
//   1. 后端返回的字段（behavior/citations）与聊天页已有的渲染结构不同，适配放在这里，
//      页面只管展示，不关心后端形态。
//   2. 所有请求失败都 resolve 成 { ok: false }，不 reject——页面据此回退到本地演示，
//      服务器没开也不会白屏。
//   3. session_id 存在本地，用于多轮承接（后端据此拼上一轮问题）。

const BASE_URL = 'http://127.0.0.1:8000';   // 换服务器/域名只改这一行
const SESSION_KEY = 'campus_assistant_session';
const TIMEOUT = 15000;   // 冷启动要加载模型，8 秒会误判超时

function sessionId() {
  let id = wx.getStorageSync(SESSION_KEY);
  if (!id) {
    id = 'mp-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    wx.setStorageSync(SESSION_KEY, id);
  }
  return id;
}

function resetSession() {
  wx.removeStorageSync(SESSION_KEY);
}

function request(path, method, data) {
  return new Promise((resolve) => {
    wx.request({
      url: BASE_URL + path,
      method: method,
      data: data,
      timeout: TIMEOUT,
      header: { 'Content-Type': 'application/json' },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve({ ok: true, data: res.data });
        } else {
          const body = res.data || {};
          resolve({ ok: false, error: body.message || body.code || ('HTTP ' + res.statusCode) });
        }
      },
      fail(err) {
        resolve({ ok: false, error: (err && err.errMsg) || '网络不可用' });
      }
    });
  });
}

function health() { return request('/v1/health', 'GET'); }

function ask(question, history) {
  return request('/v1/ask', 'POST', {
    question: question,
    session_id: sessionId(),
    channel: 'miniprogram',
    history: history || []
  });
}

function feedback(payload) { return request('/v1/feedback', 'POST', payload); }

// 后端 behavior 五档 → 聊天页的三种展示形态
const KIND = {
  answer: 'answer',
  answer_with_caveat: 'answer',
  clarify: 'clarify',
  refuse_noanswer: 'fallback',
  refuse_boundary: 'fallback'
};

function toMessage(resp) {
  const citations = resp.citations || [];
  const first = citations[0] || null;
  const boundary = resp.boundary || null;
  const channel = boundary
    ? ((boundary.channel && boundary.channel.note) || boundary.message || '')
    : '';
  return {
    kind: KIND[resp.behavior] || 'fallback',
    text: resp.answer,
    // 正文过长时先折叠，避免一条回答占满整屏
    collapsed: String(resp.answer || '').length > 200,
    title: first ? (first.article || '') : '',
    steps: [],
    channel: channel,
    source: first ? first.source : '',
    // 后端知识块不在小程序本地知识库里，因此不提供“查看指南”跳转
    knowledgeId: '',
    version: first ? first.version : 0,
    updatedAt: resp.knowledge_version || '',
    page: first ? first.page_start : 0,
    citations: citations.map((c) => ({
      chunkId: c.chunk_id,
      article: c.article || '',
      page: c.page_start || 0,
      doc: c.doc || '',
      source: c.source || ''
    })),
    scope: '杭州电子科技大学 · 2017年版手册口径',
    suggestions: resp.suggestions || [],
    contextual: false,
    isDemo: false,
    behavior: resp.behavior,
    confidence: resp.confidence,
    remote: true
  };
}

module.exports = { BASE_URL, health, ask, feedback, toMessage, sessionId, resetSession };
