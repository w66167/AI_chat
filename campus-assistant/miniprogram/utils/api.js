// 后端接口封装。全小程序只有这一个文件联网。
//
//   1. 登录：wx.login 拿 code → POST /v1/auth/login → 令牌存本机，之后每个请求带上。
//      后端配了小程序 AppID / AppSecret 就走真实微信登录；没配时按设备号发开发账号，
//      所以这里两样都上报，由后端决定用哪个。
//   2. 身份不由小程序上报：能查什么由后端按令牌认定，这里不传 identity_type。
//   3. 所有请求都 resolve 成 { ok, data } 或 { ok: false, error, code }，不 reject——
//      页面据此显示「连不上服务」并给重试，而不是白屏。
const store = require('./store');

const BASE_URL = 'http://127.0.0.1:8000';   // 换服务器 / 域名只改这一行（真机必须是 HTTPS）
const TIMEOUT = 30000;                      // 大模型生成一般 2–6 秒，留足余量

function send(path, method, data, token) {
  return new Promise((resolve) => {
    const header = { 'Content-Type': 'application/json' };
    if (token) header.Authorization = 'Bearer ' + token;
    wx.request({
      url: BASE_URL + path,
      method: method,
      data: data,
      timeout: TIMEOUT,
      header: header,
      success(res) {
        const body = res.data || {};
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve({ ok: true, status: res.statusCode, data: body });
        } else {
          resolve({ ok: false, status: res.statusCode, code: body.code || '',
            error: body.message || ('服务返回 ' + res.statusCode) });
        }
      },
      fail() {
        resolve({ ok: false, status: 0, code: 'NETWORK', error: '连不上服务，请检查网络后重试' });
      }
    });
  });
}

function wxCode() {
  return new Promise((resolve) => {
    // 游客 AppID 或开发者工具里 wx.login 可能失败，失败就只带设备号
    try { wx.login({ success: (res) => resolve(res.code || ''), fail: () => resolve('') }); }
    catch (error) { resolve(''); }
  });
}

let pendingLogin = null;
function login() {
  if (!pendingLogin) {
    pendingLogin = wxCode()
      .then((code) => send('/v1/auth/login', 'POST', { code: code, device_id: store.deviceId() }))
      .then((res) => {
        pendingLogin = null;
        if (res.ok) store.setSession(res.data);
        return res;
      });
  }
  return pendingLogin;
}

function ensureLogin() {
  return store.token() ? Promise.resolve({ ok: true }) : login();
}

// 带令牌请求；令牌失效（401）时重新登录一次再试。
function request(path, method, data) {
  return ensureLogin().then((signed) => {
    if (!signed.ok) return signed;
    return send(path, method, data, store.token()).then((res) => {
      if (res.status !== 401) return res;
      store.clearToken();
      return login().then((again) => (again.ok ? send(path, method, data, store.token()) : again));
    });
  });
}

function query(params) {
  return Object.keys(params).map((key) => key + '=' + encodeURIComponent(params[key])).join('&');
}

// ---------------------------------------------------------------- 接口
function health() { return send('/v1/health', 'GET'); }
function me() {
  return request('/v1/me', 'GET').then((res) => { if (res.ok) store.setSession(res.data); return res; });
}
function bindIdentity(identityType, code) {
  return request('/v1/me/identity', 'POST', { identity_type: identityType, code: code || '' })
    .then((res) => { if (res.ok) store.setSession(res.data); return res; });
}
function ask(question, previousQuestion, sessionId) {
  return request('/v1/ask', 'POST', {
    question: question,
    session_id: sessionId || undefined,
    channel: 'miniprogram',
    // 追问承接：只带上一轮的问题，由后端决定是否使用
    history: previousQuestion ? [{ question: previousQuestion }] : []
  });
}
function feedback(payload) { return request('/v1/feedback', 'POST', payload); }
function suggestions() { return request('/v1/suggestions', 'GET'); }
function catalog() { return request('/v1/handbook/catalog', 'GET'); }
function doc(index) { return request('/v1/handbook/doc?' + query({ index: index }), 'GET'); }
function article(chunkId) { return request('/v1/handbook/article?' + query({ id: chunkId }), 'GET'); }
function search(keyword) { return request('/v1/handbook/search?' + query({ q: keyword }), 'GET'); }
function history() { return request('/v1/history', 'GET'); }
function clearHistory() { return request('/v1/history/clear', 'POST', {}); }

// ---------------------------------------------------------------- 回答 → 页面消息
// 后端 behavior 五档 → 页面的三种展示形态
const KIND = {
  answer: 'answer',
  answer_with_caveat: 'answer',
  clarify: 'clarify',
  refuse_noanswer: 'none',
  refuse_boundary: 'boundary'
};

function citation(item) {
  return {
    chunkId: item.chunk_id,
    doc: item.doc || '',
    article: item.article || '',
    page: item.page_start || 0,
    kbName: (item.kb && item.kb.name) || ''
  };
}

function toMessage(resp) {
  const mode = resp.answer_mode || '';
  let text = String(resp.answer || '');
  // 条文原文模式下后端在正文后附了一行「出处：…」，下面的条文签已经给了同样的信息
  if (mode === 'excerpt') text = text.replace(/\n\n出处：[^\n]*/, '');
  const boundary = resp.boundary || null;
  return {
    kind: KIND[resp.behavior] || 'none',
    behavior: resp.behavior,
    text: text,
    mode: mode,                       // generated：依据条文整理；excerpt：条文原文
    degraded: !!resp.degraded,
    citations: (resp.citations || []).map(citation),
    suggestions: resp.suggestions || [],
    note: boundary && boundary.channel ? (boundary.channel.note || '') : '',
    pending: resp.kb_pending || [],
    sessionId: resp.session_id || '',
    traceId: resp.trace_id || ''
  };
}

module.exports = {
  BASE_URL, login, ensureLogin, health, me, bindIdentity, ask, feedback, suggestions,
  catalog, doc, article, search, history, clearHistory, toMessage
};
