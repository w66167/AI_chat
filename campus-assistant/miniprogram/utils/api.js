// 后端 API 封装。
// 设计要点：
//   1. 后端返回的字段（behavior/citations）与聊天页已有的渲染结构不同，适配放在这里，
//      页面只管展示，不关心后端形态。
//   2. 所有请求失败都 resolve 成 { ok: false }，不 reject——页面据此回退到本地演示，
//      服务器没开也不会白屏。
//   3. session_id 存在本地，用于多轮承接（后端据此拼上一轮问题）。

const BASE_URL = 'http://127.0.0.1:8000';   // 换服务器/域名只改这一行
const ONLINE_MODE = false;                  // true：在线优先；false：完全使用本地知识
const SESSION_KEY = 'campus_assistant_session';
const TIMEOUT = 15000;   // 冷启动要加载模型，8 秒会误判超时
const LOCAL_MODE_RESULT = { ok: false, error: 'LOCAL_MODE' };

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

function health() {
  if (!ONLINE_MODE) return Promise.resolve(LOCAL_MODE_RESULT);
  return request('/v1/health', 'GET');
}

function ask(question, history, identityType) {
  if (!ONLINE_MODE) return Promise.resolve(LOCAL_MODE_RESULT);
  // FR-16：身份适用范围由客户端显式上报（guest / student / teacher / staff），
  // 服务端按此过滤知识；缺省按游客处理，宁可少答也不越权。
  return request('/v1/ask', 'POST', {
    question: question,
    session_id: sessionId(),
    channel: 'miniprogram',
    scope: { identity_type: identityType || 'guest' },
    history: history || []
  });
}

function feedback(payload) {
  if (!ONLINE_MODE) return Promise.resolve(LOCAL_MODE_RESULT);
  return request('/v1/feedback', 'POST', payload);
}

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
  // 后端每条引用都带所属知识库（kb），这里把第一条的知识库作为本条回答的来源展示。
  const kb = (first && first.kb) || null;
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
    article: first ? (first.article || '') : '',
    page: first ? (first.page_start || 0) : 0,
    kbId: kb ? kb.id : '',
    libraryName: kb ? kb.name : '',
    libraryVersion: kb ? (kb.version || '') : '',
    libraryUpdatedAt: kb ? (kb.updated_at || '') : '',
    libraryIndexReady: kb ? !!kb.index_ready : false,
    // 后端知识块不在小程序本地知识库里，因此不提供“查看指南”跳转
    knowledgeId: '',
    version: first ? first.version : 0,
    updatedAt: resp.knowledge_version || '',
    citations: citations.map((c) => ({
      chunkId: c.chunk_id,
      article: c.article || '',
      page: c.page_start || 0,
      doc: c.doc || '',
      source: c.source || '',
      kbId: (c.kb && c.kb.id) || '',
      kbName: (c.kb && c.kb.name) || ''
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

module.exports = { BASE_URL, ONLINE_MODE, health, ask, feedback, toMessage, sessionId, resetSession };
