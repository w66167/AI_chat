// 后端接口封装。全小程序只有这一个文件联网。
//
//   1. 登录：用户选择角色 → wx.login → 后端认证及身份校验 → 保存完整会话。
//      后端配了小程序 AppID / AppSecret 就走真实微信登录；没配时按设备号发开发账号，
//      所以这里两样都上报，由后端决定用哪个。
//   2. 角色仅在登录时提交给身份绑定接口；业务请求的权限仍由后端按令牌认定。
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
let sessionVersion = 0;
let redirecting = false;

function cancelled() {
  return { ok: false, code: 'SESSION_CHANGED', error: '登录状态已变化，请重新操作' };
}

function clearPending() {
  const app = getApp().globalData;
  app.pendingQuestion = '';
  app.pendingDraft = '';
  app.pendingCategory = '';
}

function openLogin() {
  if (redirecting) return;
  redirecting = true;
  wx.reLaunch({ url: '/pages/login/login', complete: () => { redirecting = false; } });
}

function signOut() {
  // 让退出前的登录、角色绑定、页面请求全部失效，迟到的响应不能恢复旧身份。
  sessionVersion += 1;
  pendingLogin = null;
  store.signOut();
  clearPending();
  openLogin();
}

function requireLogin() {
  if (store.isLoggedIn()) return true;
  clearPending();
  openLogin();
  return false;
}

function relogin() {
  wx.showModal({
    title: '重新选择登录身份？',
    content: '将退出当前登录并清除本机对话，然后返回登录页选择身份。',
    confirmText: '重新登录',
    success: (res) => {
      if (!res.confirm) return;
      try { signOut(); } catch (error) { wx.showToast({ title: error.message, icon: 'none' }); }
    }
  });
}

function login(identityType, code) {
  if (!store.roles.some((role) => role.identityType === identityType)) {
    return Promise.resolve({ ok: false, code: 'BAD_IDENTITY', error: '请选择登录身份' });
  }
  if (store.isLoggedIn()) {
    return Promise.resolve({ ok: false, code: 'ALREADY_LOGGED_IN', error: '请先退出登录，再选择其他身份' });
  }
  if (pendingLogin) return pendingLogin;
  const version = sessionVersion;
  const task = wxCode()
    .then((wxLoginCode) => {
      if (version !== sessionVersion) return cancelled();
      return send('/v1/auth/login', 'POST', { code: wxLoginCode, device_id: store.deviceId() });
    })
    .then((signed) => {
      if (version !== sessionVersion) return cancelled();
      if (!signed.ok) return signed;
      // 中间令牌只留在本次请求里。教师口令错误等失败不会留下可进入首页的会话。
      return send('/v1/me/identity', 'POST', { identity_type: identityType, code: code || '' }, signed.data.token)
        .then((bound) => {
          if (version !== sessionVersion) return cancelled();
          if (!bound.ok) return bound;
          if (bound.data.identity_type !== identityType) {
            return { ok: false, code: 'IDENTITY_MISMATCH', error: '登录身份校验失败，请重试' };
          }
          const data = Object.assign({}, bound.data, { token: signed.data.token });
          store.completeLogin(data);
          clearPending();
          return { ok: true, data };
        });
    })
    .catch((error) => ({ ok: false, code: 'LOGIN_FAILED', error: error.message || '登录失败，请重试' }));
  pendingLogin = task;
  task.then(() => { if (pendingLogin === task) pendingLogin = null; });
  return task;
}

function ensureLogin() {
  return Promise.resolve(requireLogin() ? { ok: true }
    : { ok: false, code: 'LOGIN_REQUIRED', error: '请先在登录页选择身份并登录' });
}

// 业务请求不会静默创建游客会话；令牌失效时回到登录页重新选择身份。
function request(path, method, data, updateProfile) {
  if (!requireLogin()) {
    return Promise.resolve({ ok: false, code: 'LOGIN_REQUIRED', error: '请先在登录页选择身份并登录' });
  }
  const version = sessionVersion;
  const token = store.token();
  return send(path, method, data, token).then((res) => {
    if (version !== sessionVersion || token !== store.token() || !store.isLoggedIn()) return cancelled();
    if (res.status === 401) {
      signOut();
      return { ok: false, status: 401, code: 'LOGIN_REQUIRED', error: '登录已失效，请重新登录' };
    }
    // 在同一轮有效性检查后保存，避免旧 /me 响应覆盖退出后建立的新身份。
    if (res.ok && updateProfile) store.setSession(res.data);
    return res;
  });
}

function query(params) {
  return Object.keys(params).map((key) => key + '=' + encodeURIComponent(params[key])).join('&');
}

// ---------------------------------------------------------------- 接口
function health() { return send('/v1/health', 'GET'); }
function me() { return request('/v1/me', 'GET', undefined, true); }
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
  BASE_URL, login, ensureLogin, requireLogin, signOut, relogin, health, me, ask, feedback, suggestions,
  catalog, doc, article, search, history, clearHistory, toMessage
};
