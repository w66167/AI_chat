const seed = require('../data/knowledge');
const KEY = 'campus_assistant_demo_v1';
const roles = [
  { id: 'student', name: '学生', description: '提问、查看指南、评价回答' },
  { id: 'maintainer', name: '知识维护人员', description: '新建、修订知识并提交审核' },
  { id: 'reviewer', name: '知识审核员', description: '审核、驳回并发布知识' }
];

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function date() { return new Date().toISOString().slice(0, 10); }
function id(prefix) { return prefix + '-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7); }
function fresh() {
  return { schemaVersion: 1, role: 'student', knowledge: clone(seed.knowledge), drafts: [clone(seed.sampleDraft)], messages: [], feedback: [], audit: [] };
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
function role() { return roles.find((item) => item.id === read().role) || roles[0]; }
function requireRole(db, expected) {
  if (db.role !== expected) throw new Error('请先在“我的”切换到对应演示角色。');
}
function log(db, action, title) {
  db.audit.unshift({ id: id('log'), action, title, actor: db.role, time: new Date().toISOString() });
  db.audit = db.audit.slice(0, 100);
}
function setRole(value) {
  if (!roles.some((item) => item.id === value)) throw new Error('演示角色不存在。');
  const db = read(); db.role = value; write(db);
}
function getKnowledge() { return read().knowledge.filter((item) => item.status === 'published'); }
function getItem(value) { return getKnowledge().find((item) => item.id === value); }
function appendMessages(items) {
  const db = read();
  db.messages = db.messages.concat(items).slice(-120);
  const retained = new Set(db.messages.map((item) => item.id));
  db.feedback = db.feedback.filter((item) => retained.has(item.messageId));
  write(db);
}
function clearMessages() { const db = read(); db.messages = []; db.feedback = []; write(db); }
function setFeedback(messageId, value) {
  const db = read();
  if (!['resolved', 'unresolved'].includes(value)) throw new Error('请选择有效的评价。');
  const message = db.messages.find((item) => item.id === messageId && item.speaker === 'assistant');
  if (!message) throw new Error('这条回答已清除，请重新提问。');
  message.feedback = value;
  db.feedback = db.feedback.filter((item) => item.messageId !== messageId);
  db.feedback.push({ messageId, value, question: message.question, knowledgeId: message.knowledgeId || '', version: message.version || 0, createdAt: date() });
  write(db);
}
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
    const published = {
      id: target ? target.id : id('kb'), title: draft.title, category: draft.category, aliases: draft.aliases,
      answer: draft.answer, steps: draft.steps, channel: draft.channel, source: draft.source,
      scope: draft.scope, version: target ? target.version + 1 : 1, updatedAt: date(), status: 'published', isDemo: true
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
  return { knowledge: db.knowledge.length, questions: db.messages.filter((m) => m.speaker === 'user').length,
    pending: db.drafts.filter((d) => d.status === 'pending').length,
    resolved: db.feedback.filter((f) => f.value === 'resolved').length,
    unresolved: db.feedback.filter((f) => f.value === 'unresolved').length };
}
function reset() { return write(fresh()); }

module.exports = { init, read, role, roles, setRole, getKnowledge, getItem, appendMessages, clearMessages, setFeedback,
  getDrafts, saveDraft, submitDraft, reviewDraft, stats, reset, id, categories: seed.categories };
