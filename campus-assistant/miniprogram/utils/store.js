const seed = require('../data/knowledge');
const visitorGuide = require('../data/visitor_guide_local');
const registry = require('../data/libraries');
const KEY = 'campus_assistant_demo_v1';
const DEFAULT_ROLE = 'student';

// 用户端小程序只有三种使用者身份：游客、学生、教师/行政人员。
// 「知识维护人员 / 知识审核员」是对系统负责而不是使用系统的内部角色
// （注册表里 app === false），因此不进用户端：没有身份切换、没有工作台页面。
// 知识起草、提交、审核、发布改由管理端流程完成，见 knowledge_base/scripts/kb_admin.py。
// identityType 取值与后端 schemas.IdentityType 一致（guest / student / teacher / staff）。
const roles = registry.identities.filter((item) => item.app === true).map((item) => ({
  id: item.id,
  name: item.name,
  identityType: item.identity_type,
  avatar: item.avatar,
  history: !!item.history,
  description: item.description
}));

// 知识库：audience 决定哪些身份能访问，条目通过 kbId 归属到知识库。
// audience 里的 staff 覆盖两个管理端角色，用户端用不到，但过滤逻辑保持同一套。
const libraries = registry.libraries;
const DEFAULT_KB = seed.DEFAULT_KB;

// 游客的匿名会话：只放在内存里，切换身份、清除会话或退出小程序即失效。
// 这样“退出或清除后不能凭旧页面状态重新取得历史内容”（需求文档 2.1、FR-05）。
let guestSession = { messages: [], feedback: [] };
function emptyGuestSession() { return { messages: [], feedback: [] }; }

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function date() { return new Date().toISOString().slice(0, 10); }
function id(prefix) { return prefix + '-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7); }
function bundledKnowledge() {
  return clone(seed.knowledge).concat(clone(visitorGuide.entries || []));
}
function mergeVisitorEntries(db) {
  const generated = visitorGuide.entries || [];
  if (!generated.length) return db;
  // 游客库随版本更新；旧缓存里保留其它知识，但同名游客条目以当前打包版本为准。
  const generatedIds = new Set(generated.map((item) => item.id));
  db.knowledge = db.knowledge.filter((item) => !generatedIds.has(item.id)).concat(clone(generated));
  return db;
}
function fresh() {
  // 只有用户侧数据：身份、知识、会话、反馈。草稿与审核记录不属于用户端。
  return { schemaVersion: 1, role: DEFAULT_ROLE, knowledge: bundledKnowledge(), messages: [], feedback: [] };
}
function write(db) {
  // 写入成功后页面才更新，避免空间不足时出现“保存成功”的假象。
  try { wx.setStorageSync(KEY, db); } catch (error) { throw new Error('本地保存失败，请清理开发者工具缓存空间后重试。'); }
  return db;
}
function read() {
  const db = wx.getStorageSync(KEY);
  if (db && db.schemaVersion === 1 && Array.isArray(db.knowledge)) return mergeVisitorEntries(clone(db));
  return write(fresh());
}
function init() { return read(); }
function roleById(value) { return roles.find((item) => item.id === value) || null; }
function role() { return roleById(read().role) || roleById(DEFAULT_ROLE); }
function setRole(value) {
  if (!roles.some((item) => item.id === value)) throw new Error('演示身份不存在。');
  const db = read();
  // 身份切换后旧的匿名会话立即失效，避免把“演示切换身份”当成真实认证（需求文档 2.1）。
  if (db.role !== value) guestSession = emptyGuestSession();
  db.role = value; write(db);
}

// ---------------------------------------------------------------- 知识库与身份适用范围
function libraryById(value) { return libraries.find((item) => item.id === value) || null; }
function libraryIds() { return libraries.map((item) => item.id); }
function libraryAudience(item) {
  const library = libraryById(item && item.kbId) || libraryById(DEFAULT_KB);
  return library ? library.audience : [];
}
// 身份能访问的知识库：游客有公开指南与游客参观指南，学生再加学生手册，
// 教师再加教职工手册。管理端角色（staff）照常由后端按 identity_type 处理。
function librariesFor(current) {
  const identity = (current || role()).identityType;
  return libraries.filter((item) => item.audience.indexOf(identity) >= 0);
}
function canSee(item, current) {
  return libraryAudience(item).indexOf((current || role()).identityType) >= 0;
}
// 给条目补上「所属知识库」和展示用字段，页面与检索层都不用自己查表。
function decorate(item) {
  const library = libraryById(item.kbId) || libraryById(DEFAULT_KB);
  return Object.assign({}, item, {
    kbId: library.id,
    libraryName: library.name,
    libraryVersion: library.version,
    libraryUpdatedAt: library.updated_at,
    libraryStatus: library.content_status,
    libraryIndexReady: !!library.index_ready,
    libraryDocuments: library.documents,
    audience: library.audience,
    scope: item.scope || library.scope_text
  });
}
function getKnowledge() {
  const current = role();
  return read().knowledge.filter((item) => item.status === 'published' && canSee(item, current)).map(decorate);
}
function getItem(value) { return getKnowledge().find((item) => item.id === value); }
// 当前身份看不到的已发布知识。本地检索用它判断“范围内没有依据、范围外却明显更贴近”，
// 从而兜底，而不是拿一条不相关的公开条目硬答（需求文档 2.1 权限规则）。
function getRestrictedKnowledge() {
  const current = role();
  return read().knowledge.filter((item) => item.status === 'published' && !canSee(item, current)).map(decorate);
}
// 「我的」页的知识库清单：所有知识库 + 当前身份能不能访问 + 本机已发布的条目数。
function getLibraries() {
  const current = role();
  const published = read().knowledge.filter((item) => item.status === 'published');
  return libraries.map((library) => {
    const items = published.filter((item) => item.kbId === library.id);
    return {
      id: library.id, name: library.name, version: library.version, updatedAt: library.updated_at,
      contentStatus: library.content_status, indexReady: !!library.index_ready,
      scopeText: library.scope_text, summary: library.summary, documents: library.documents,
      visible: library.audience.indexOf(current.identityType) >= 0,
      localEntries: items.filter((item) => canSee(item, current)).length
    };
  });
}

// ---------------------------------------------------------------- 会话与反馈
// 登录身份（学生 / 教师）使用本机历史；游客只看当前匿名会话。
function getMessages() {
  const current = role();
  return current.history ? read().messages : clone(guestSession.messages);
}
function appendMessages(items) {
  const current = role();
  if (!current.history) {
    guestSession.messages = guestSession.messages.concat(items).slice(-120);
    const retained = new Set(guestSession.messages.map((item) => item.id));
    guestSession.feedback = guestSession.feedback.filter((item) => retained.has(item.messageId));
    return;
  }
  const db = read();
  db.messages = db.messages.concat(items).slice(-120);
  const retained = new Set(db.messages.map((item) => item.id));
  db.feedback = db.feedback.filter((item) => retained.has(item.messageId));
  write(db);
}
function clearMessages() {
  const current = role();
  if (!current.history) { guestSession = emptyGuestSession(); return; }
  const db = read(); db.messages = []; db.feedback = []; write(db);
}
function setFeedback(messageId, value) {
  if (!['resolved', 'unresolved'].includes(value)) throw new Error('请选择有效的评价。');
  const current = role();
  if (!current.history) {
    // 游客反馈只关联当前匿名会话，不写入本机长期档案（需求文档 2.1、3.4 反馈规则）。
    const message = guestSession.messages.find((item) => item.id === messageId && item.speaker === 'assistant');
    if (!message) throw new Error('这条回答已清除，请重新提问。');
    message.feedback = value;
    guestSession.feedback = guestSession.feedback.filter((item) => item.messageId !== messageId);
    guestSession.feedback.push({ messageId, value, question: message.question, knowledgeId: message.knowledgeId || '', version: message.version || 0, createdAt: date(), anonymous: true });
    return;
  }
  const db = read();
  const message = db.messages.find((item) => item.id === messageId && item.speaker === 'assistant');
  if (!message) throw new Error('这条回答已清除，请重新提问。');
  message.feedback = value;
  db.feedback = db.feedback.filter((item) => item.messageId !== messageId);
  db.feedback.push({ messageId, value, question: message.question, knowledgeId: message.knowledgeId || '', version: message.version || 0, createdAt: date() });
  write(db);
}
function stats() {
  const db = read();
  const current = role();
  const messages = current.history ? db.messages : guestSession.messages;
  const feedback = current.history ? db.feedback : guestSession.feedback;
  return { knowledge: getKnowledge().length, questions: messages.filter((m) => m.speaker === 'user').length,
    resolved: feedback.filter((f) => f.value === 'resolved').length,
    unresolved: feedback.filter((f) => f.value === 'unresolved').length };
}
function reset() { guestSession = emptyGuestSession(); return write(fresh()); }

module.exports = { init, read, role, roleById, roles, setRole, getKnowledge, getItem, getRestrictedKnowledge,
  getLibraries, libraryById, libraryIds, librariesFor,
  getMessages, appendMessages, clearMessages, setFeedback, stats, reset, id,
  categories: seed.categories, DEFAULT_KB: DEFAULT_KB };
