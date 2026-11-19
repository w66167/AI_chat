// 本机状态：登录凭据、身份资料、当前对话。
//
// 知识不在这里——问答、手册目录和条文原文都来自后端，小程序不再随包带任何知识内容。
// 这里只管三件事：
//   1. 登录令牌与设备号（令牌由后端签发，身份由后端认定，本机只是缓存一份用于显示）
//   2. 身份资料：是谁、什么身份、能查哪些知识库（后端 /v1/me 的返回）
//   3. 当前对话：在校身份存本机，游客只放内存
const registry = require('../data/libraries');

const KEY = 'campus_assistant_v2';
const MAX_MESSAGES = 120;

// 用户端只有三种使用者身份；知识维护人员 / 知识审核员是管理端角色（注册表里 app === false），
// 不进小程序，见 knowledge_base/scripts/kb_admin.py。
const roles = registry.identities.filter((item) => item.app === true).map((item) => ({
  id: item.id,
  name: item.name,
  identityType: item.identity_type,
  avatar: item.avatar,
  history: !!item.history,
  description: item.description
}));

// 游客的对话只放在内存里：换身份、点「新对话」或退出小程序即失效（需求文档 FR-05）。
let guestMessages = [];

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function id(prefix) { return prefix + '-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }
function fresh() {
  return { schemaVersion: 2, deviceId: '', token: '', profile: null, loginComplete: false, messages: [] };
}
function write(db) {
  // 写入成功后页面才更新，避免空间不足时出现「已保存」的假象。
  try { wx.setStorageSync(KEY, db); } catch (error) { throw new Error('本机存储空间不足，请清理后重试。'); }
  return db;
}
function read() {
  const db = wx.getStorageSync(KEY);
  if (db && db.schemaVersion === 2) return clone(db);
  return write(fresh());
}
function init() { return read(); }

// ---------------------------------------------------------------- 登录凭据
function deviceId() {
  const db = read();
  if (!db.deviceId) {
    db.deviceId = 'mp-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
    write(db);
  }
  return db.deviceId;
}
function token() { return read().token || ''; }
function clearToken() { const db = read(); db.token = ''; db.loginComplete = false; write(db); }
function isLoggedIn() {
  const db = read();
  // 老版本的静默登录缓存也必须先走一次新登录页，明确选择本次使用的身份。
  return !!(db.loginComplete && db.token && db.profile && db.profile.user);
}

// 后端返回的登录 / 身份结果统一从这里落地。
// 身份变了就清空当前对话：对话里可能有新身份无权查看的条文。
function setSession(payload, complete) {
  const db = read();
  const before = db.profile ? db.profile.identity_type : 'guest';
  const beforeUser = db.profile && db.profile.user ? db.profile.user.id : '';
  if (payload.token) db.token = payload.token;
  db.profile = {
    user: payload.user || null,
    identity_type: payload.identity_type || 'guest',
    auth_mode: payload.auth_mode || '',
    binding: payload.binding || {},
    libraries: payload.libraries || []
  };
  const afterUser = db.profile.user ? db.profile.user.id : '';
  if (before !== db.profile.identity_type || beforeUser !== afterUser) { db.messages = []; guestMessages = []; }
  if (complete) db.loginComplete = true;
  write(db);
  return db.profile;
}
// 认证和所选身份的服务端校验都完成之后，才一次性保存可用会话。
function completeLogin(payload) { return setSession(payload, true); }

// ---------------------------------------------------------------- 身份
function identity() {
  const profile = read().profile;
  return (profile && profile.identity_type) || 'guest';
}
function roleByIdentity(value) { return roles.find((item) => item.identityType === value) || roles[0]; }
function role() { return roleByIdentity(identity()); }
function profile() { return read().profile; }

// 知识库清单：登录后用后端给的（带 accessible）；还没连上后端时用随包的注册表推算，
// 两者同源（knowledge_base/data/libraries.json），不会各说各话。
function libraries() {
  const current = profile();
  if (current && current.libraries.length) {
    // 介绍随小程序一同发布；旧登录缓存或尚未重启的服务不能把维护说明带回页面。
    // accessible 等权限字段仍完全使用服务端结果。
    return current.libraries.map((item) => {
      const definition = registry.libraries.find((entry) => entry.id === item.id);
      return Object.assign({}, item, { summary: definition ? definition.summary : (item.summary || '') });
    });
  }
  const who = identity();
  return registry.libraries.map((item) => ({
    id: item.id, name: item.name, version: item.version, content_status: item.content_status,
    index_ready: !!item.index_ready, audience: item.audience, summary: item.summary,
    scope_text: item.scope_text, documents: (item.documents || []).length,
    accessible: item.audience.indexOf(who) >= 0
  }));
}
function accessibleLibraries() { return libraries().filter((item) => item.accessible); }
// “可查”只列出有权限且实际接入检索的库，维护状态不作为用户端标签。
function searchableLibraries() { return accessibleLibraries().filter((item) => item.index_ready); }

// ---------------------------------------------------------------- 当前对话
function keepsHistory() { return role().history; }
function getMessages() { return keepsHistory() ? read().messages : clone(guestMessages); }
function appendMessages(items) {
  if (!keepsHistory()) {
    guestMessages = guestMessages.concat(items).slice(-MAX_MESSAGES);
    return;
  }
  const db = read();
  db.messages = db.messages.concat(items).slice(-MAX_MESSAGES);
  write(db);
}
function updateMessage(messageId, patch) {
  if (!keepsHistory()) {
    const target = guestMessages.find((item) => item.id === messageId);
    if (!target) throw new Error('这条回答已清除，请重新提问。');
    Object.assign(target, patch);
    return;
  }
  const db = read();
  const target = db.messages.find((item) => item.id === messageId);
  if (!target) throw new Error('这条回答已清除，请重新提问。');
  Object.assign(target, patch);
  write(db);
}
function clearMessages() {
  guestMessages = [];
  const db = read();
  db.messages = [];
  write(db);
}
// 退出登录：令牌、身份、对话全部清掉，设备号保留。
function signOut() {
  guestMessages = [];
  const db = read();
  write(Object.assign(fresh(), { deviceId: db.deviceId }));
}

module.exports = {
  init, read, id, roles, role, roleByIdentity, identity, profile, libraries, accessibleLibraries, searchableLibraries,
  deviceId, token, clearToken, isLoggedIn, setSession, completeLogin, signOut,
  keepsHistory, getMessages, appendMessages, updateMessage, clearMessages
};
