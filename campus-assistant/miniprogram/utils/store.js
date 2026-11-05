const seed = require('../data/knowledge');
const KEY = 'campus_assistant_demo_v1';

// 角色与《需求分析说明书》2.1 用户角色与权限表一一对应。
// identityType 取值与后端 schemas.IdentityType 一致（guest / student / teacher / staff），
// 小程序把它作为 scope.identity_type 上报，服务端据此做适用范围过滤（FR-16）。
//   workbench：能否进入知识工作台
//   history  ：是否保留跨会话个人历史；游客只保留当前匿名会话（内存，不落盘）
const roles = [
  { id: 'guest', name: '游客', identityType: 'guest', avatar: '客', workbench: false, history: false,
    description: '公开问答、指南与当前会话反馈；不提供跨会话个人历史' },
  { id: 'student', name: '学生', identityType: 'student', avatar: '学', workbench: false, history: true,
    description: '适用知识问答、本人历史与反馈；按身份范围访问，不查询他人会话' },
  { id: 'teacher', name: '教师/行政人员', identityType: 'teacher', avatar: '师', workbench: false, history: true,
    description: '问答与指南权限同学生，另可访问教师、行政人员适用知识' },
  { id: 'maintainer', name: '知识维护人员', identityType: 'staff', avatar: '维', workbench: true, history: true,
    description: '起草、修订、提交审核并维护官方途径；仅限负责范围，不能直接发布' },
  { id: 'reviewer', name: '知识审核员', identityType: 'staff', avatar: '审', workbench: true, history: true,
    description: '审核、驳回并发布知识；不能审核本人参与编写的版本' }
];
const DEFAULT_ROLE = 'student';
const AUDIENCE_KEYS = Object.keys(seed.AUDIENCE);   // public / member / teacher

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

// ---------------------------------------------------------------- 身份适用范围
// 知识条目自带的 audience 是身份白名单；旧缓存数据没有该字段时按公开知识处理。
function audienceOf(item) { return Array.isArray(item.audience) && item.audience.length ? item.audience : seed.AUDIENCE.public; }
function audienceKeyOf(item) {
  const list = audienceOf(item);
  return AUDIENCE_KEYS.find((key) => seed.AUDIENCE[key].length === list.length && seed.AUDIENCE[key].every((type) => list.indexOf(type) >= 0)) || 'public';
}
function canSee(item, current) { return audienceOf(item).indexOf((current || role()).identityType) >= 0; }
function getKnowledge() {
  const current = role();
  return read().knowledge.filter((item) => item.status === 'published' && canSee(item, current));
}
function getItem(value) { return getKnowledge().find((item) => item.id === value); }
// 当前身份看不到的已发布知识。本地检索用它判断“范围内没有依据、范围外却明显更贴近”，
// 从而兜底，而不是拿一条不相关的公开条目硬答（需求文档 2.1 权限规则）。
function getRestrictedKnowledge() {
  const current = role();
  return read().knowledge.filter((item) => item.status === 'published' && !canSee(item, current));
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
function saveDraft(form) {
  const db = read(); requireRole(db, 'maintainer');
  ['title', 'answer', 'source', 'channel', 'scope'].forEach((key) => {
    if (!String(form[key] || '').trim()) throw new Error('请填写标题、答案、来源、咨询途径和适用范围。');
  });
  if (!seed.categories.slice(1).includes(form.category)) throw new Error('请选择知识分类。');
  const audienceKey = form.audienceKey || 'public';
  if (AUDIENCE_KEYS.indexOf(audienceKey) < 0) throw new Error('请选择有效的身份适用范围。');
  const existing = form.id ? db.drafts.find((item) => item.id === form.id) : null;
  if (form.id && !existing) throw new Error('草稿不存在，请刷新后重试。');
  if (existing && (existing.author !== db.role || !['draft', 'rejected'].includes(existing.status))) throw new Error('只能编辑本人草稿或被退回的知识。');
  const target = form.targetId ? db.knowledge.find((item) => item.id === form.targetId) : null;
  if (form.targetId && !target) throw new Error('原知识不存在。');
  if (!existing && target && db.drafts.some((item) => item.targetId === target.id && ['draft', 'pending', 'rejected'].includes(item.status))) throw new Error('这条知识已有修订，请先处理已有草稿。');
  const draft = {
    id: existing ? existing.id : id('draft'), targetId: target ? target.id : '',
    baseVersion: existing ? existing.baseVersion : target ? target.version : 0,
    title: form.title.trim(), answer: form.answer.trim(), category: form.category,
    aliases: (form.aliases || '').split(/[\n,，]/).map((v) => v.trim()).filter(Boolean),
    steps: (form.steps || '').split('\n').map((v) => v.trim()).filter(Boolean),
    channel: form.channel.trim(), source: form.source.trim(), scope: form.scope.trim(),
    audienceKey: audienceKey,
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
    const audienceKey = AUDIENCE_KEYS.indexOf(draft.audienceKey) >= 0 ? draft.audienceKey : 'public';
    const published = {
      id: target ? target.id : id('kb'), title: draft.title, category: draft.category, aliases: draft.aliases,
      answer: draft.answer, steps: draft.steps, channel: draft.channel, source: draft.source,
      scope: draft.scope || seed.SCOPE_TEXT[audienceKey], audience: seed.AUDIENCE[audienceKey],
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

module.exports = { init, read, role, roleById, roles, setRole, getKnowledge, getItem, getRestrictedKnowledge, canEnterWorkbench,
  audienceKeyOf, getMessages, appendMessages, clearMessages, setFeedback, getDrafts, saveDraft, submitDraft, reviewDraft, stats, reset, id,
  categories: seed.categories, AUDIENCE: seed.AUDIENCE, SCOPE_TEXT: seed.SCOPE_TEXT };
