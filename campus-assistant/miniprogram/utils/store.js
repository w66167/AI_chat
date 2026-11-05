const seed = require('../data/knowledge');
const registry = require('../data/libraries');
const KEY = 'campus_assistant_demo_v1';
const DEFAULT_ROLE = 'student';

// 身份清单来自知识库注册表（knowledge_base/data/libraries.json → data/libraries.js），
// 与后端 backend/app/libraries.py 读的是同一份定义，避免两边各写一套身份。
// identityType 取值与后端 schemas.IdentityType 一致（guest / student / teacher / staff）。
const roles = registry.identities.map((item) => ({
  id: item.id,
  name: item.name,
  identityType: item.identity_type,
  avatar: item.avatar,
  workbench: !!item.workbench,
  history: !!item.history,
  description: item.description
}));

// 知识库：audience 决定哪些身份能访问，条目通过 kbId 归属到知识库。
const libraries = registry.libraries;
const DEFAULT_KB = seed.DEFAULT_KB;

// 游客的匿名会话：只放在内存里，切换身份、清除会话或退出小程序即失效。
// 这样“退出或清除后不能凭旧页面状态重新取得历史内容”（需求文档 2.1、FR-05）。
let guestSession = { messages: [], feedback: [] };
function emptyGuestSession() { return { messages: [], feedback: [] }; }

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function date() { return new Date().toISOString().slice(0, 10); }
function id(prefix) { return prefix + '-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7); }
function fresh() {
  return { schemaVersion: 1, role: DEFAULT_ROLE, knowledge: clone(seed.knowledge), drafts: [clone(seed.sampleDraft)], messages: [], feedback: [], audit: [] };
}
function write(db) {
  // 写入成功后页面才更新，避免空间不足时出现“保存成功”的假象。
  try { wx.setStorageSync(KEY, db); } catch (error) { throw new Error('本地保存失败，请清理开发者工具缓存空间后重试。'); }
  return db;
}
function read() {
  const db = wx.getStorageSync(KEY);
  if (db && db.schemaVersion === 1 && Array.isArray(db.knowledge)) return clone(db);
  return write(fresh());
}
function init() { return read(); }
function roleById(value) { return roles.find((item) => item.id === value) || null; }
function role() { return roleById(read().role) || roleById(DEFAULT_ROLE); }
function requireRole(db, expected) {
  if (db.role !== expected) throw new Error('请先在“我的”切换到对应演示角色。');
}
function log(db, action, title) {
  db.audit.unshift({ id: id('log'), action, title, actor: db.role, time: new Date().toISOString() });
  db.audit = db.audit.slice(0, 100);
}
function setRole(value) {
  if (!roles.some((item) => item.id === value)) throw new Error('演示角色不存在。');
  const db = read();
  // 身份切换后旧的匿名会话立即失效，避免把“演示切换角色”当成真实认证（需求文档 2.1）。
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
// 身份能访问的知识库：游客只有公开指南，学生再加学生手册，教师再加教职工手册，维护/审核看全部。
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
    libraryUpdatedAt: library.updatedAt,
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
function canEnterWorkbench() { return !!role().workbench; }

// ---------------------------------------------------------------- 会话与反馈
// 登录身份（学生 / 教师 / 维护 / 审核）使用本机历史；游客只看当前匿名会话。
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

// ---------------------------------------------------------------- 知识维护与审核
function getDrafts() {
  const db = read();
  return db.role === 'reviewer' ? db.drafts : db.role === 'maintainer' ? db.drafts.filter((item) => item.author === db.role) : [];
}
function draftKbId(value) {
  return libraryById(value) ? value : DEFAULT_KB;
}
function saveDraft(form) {
  const db = read(); requireRole(db, 'maintainer');
  const target = form.targetId ? db.knowledge.find((item) => item.id === form.targetId) : null;
  // 修订已有条目时沿用原条目所属的知识库；新建时必须明确指定。
  const kbId = form.kbId || (target && target.kbId) || '';
  if (!libraryById(kbId)) throw new Error('请选择知识条目所属的知识库。');
  ['title', 'answer', 'source', 'channel', 'scope'].forEach((key) => {
    if (!String(form[key] || '').trim()) throw new Error('请填写标题、答案、来源、咨询途径和适用范围。');
  });
  if (!seed.categories.slice(1).includes(form.category)) throw new Error('请选择知识分类。');
  const existing = form.id ? db.drafts.find((item) => item.id === form.id) : null;
  if (form.id && !existing) throw new Error('草稿不存在，请刷新后重试。');
  if (existing && (existing.author !== db.role || !['draft', 'rejected'].includes(existing.status))) throw new Error('只能编辑本人草稿或被退回的知识。');
  if (form.targetId && !target) throw new Error('原知识不存在。');
  if (!existing && target && db.drafts.some((item) => item.targetId === target.id && ['draft', 'pending', 'rejected'].includes(item.status))) throw new Error('这条知识已有修订，请先处理已有草稿。');
  const draft = {
    id: existing ? existing.id : id('draft'), targetId: target ? target.id : '',
    baseVersion: existing ? existing.baseVersion : target ? target.version : 0,
    title: form.title.trim(), answer: form.answer.trim(), category: form.category,
    aliases: (form.aliases || '').split(/[\n,，]/).map((v) => v.trim()).filter(Boolean),
    steps: (form.steps || '').split('\n').map((v) => v.trim()).filter(Boolean),
    channel: form.channel.trim(), source: form.source.trim(), scope: form.scope.trim(),
    kbId: kbId, article: (form.article || '').trim(), page: Number(form.page) || 0,
    author: db.role, authorName: '知识维护人员', status: 'draft', isDemo: true, reason: '', updatedAt: date()
  };
  if (existing) db.drafts[db.drafts.indexOf(existing)] = draft; else db.drafts.unshift(draft);
  log(db, '保存草稿', draft.title); write(db); return draft;
}
function submitDraft(value) {
  const db = read(); requireRole(db, 'maintainer');
  const draft = db.drafts.find((item) => item.id === value);
  if (!draft || draft.author !== db.role || !['draft', 'rejected'].includes(draft.status)) throw new Error('这条草稿不能提交。');
  draft.status = 'pending'; draft.reason = ''; draft.updatedAt = date();
  log(db, '提交审核', draft.title); write(db);
}
function reviewDraft(value, approved, reason) {
  const db = read(); requireRole(db, 'reviewer');
  const draft = db.drafts.find((item) => item.id === value);
  if (!draft || draft.status !== 'pending') throw new Error('该知识当前不在待审核状态。');
  if (draft.author === db.role) throw new Error('不能审核自己起草的知识。');
  if (!approved) {
    if (!String(reason || '').trim()) throw new Error('请填写退回原因。');
    draft.status = 'rejected'; draft.reason = reason.trim(); log(db, '退回知识', draft.title);
  } else {
    const target = draft.targetId ? db.knowledge.find((item) => item.id === draft.targetId) : null;
    if (draft.targetId && (!target || target.version !== draft.baseVersion)) throw new Error('原知识版本已变化，请重新修订后提交。');
    const kbId = draftKbId(draft.kbId);
    const published = {
      id: target ? target.id : id('kb'), kbId: kbId, title: draft.title, category: draft.category, aliases: draft.aliases,
      answer: draft.answer, steps: draft.steps, channel: draft.channel, source: draft.source,
      article: draft.article || '', page: draft.page || 0,
      scope: draft.scope || (libraryById(kbId) || {}).scope_text || '',
      version: target ? target.version + 1 : 1, updatedAt: date(), status: 'published', isDemo: true
    };
    if (target) db.knowledge[db.knowledge.indexOf(target)] = published; else db.knowledge.unshift(published);
    // 审核单留存本次提交内容；旧问答也保留回答时的版本快照。
    draft.status = 'approved'; draft.publishedVersion = published.version;
    log(db, '审核发布 v' + published.version, draft.title);
  }
  write(db);
}
function stats() {
  const db = read();
  const current = role();
  const messages = current.history ? db.messages : guestSession.messages;
  const feedback = current.history ? db.feedback : guestSession.feedback;
  return { knowledge: getKnowledge().length, questions: messages.filter((m) => m.speaker === 'user').length,
    pending: db.drafts.filter((d) => d.status === 'pending').length,
    resolved: feedback.filter((f) => f.value === 'resolved').length,
    unresolved: feedback.filter((f) => f.value === 'unresolved').length };
}
function reset() { guestSession = emptyGuestSession(); return write(fresh()); }

module.exports = { init, read, role, roleById, roles, setRole, getKnowledge, getItem, getRestrictedKnowledge,
  getLibraries, libraryById, libraryIds, librariesFor, canEnterWorkbench,
  getMessages, appendMessages, clearMessages, setFeedback, getDrafts, saveDraft, submitDraft, reviewDraft, stats, reset, id,
  categories: seed.categories, DEFAULT_KB: DEFAULT_KB };
