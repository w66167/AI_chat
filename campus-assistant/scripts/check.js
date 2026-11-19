// 小程序本地检查：不需要后端、不需要开发者工具。
//   node scripts/check.js
// 检查项目结构与语法、联网规则、「不随包带知识」的约束、页面事件处理函数是否齐全，
// 以及 utils/store.js 的登录凭据、身份与对话逻辑。
// 页面接真实后端的联调在 backend/tests/smoke_miniprogram.js。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const mini = path.join(root, 'miniprogram');
let cache = {};
let failWrite = false;
global.wx = {
  getStorageSync: (key) => (cache[key] ? JSON.parse(JSON.stringify(cache[key])) : ''),
  setStorageSync: (key, value) => {
    if (failWrite) throw new Error('storage full');
    cache[key] = JSON.parse(JSON.stringify(value));
  }
};
const store = require('../miniprogram/utils/store');
const api = require('../miniprogram/utils/api');
const registry = require('../miniprogram/data/libraries');
const app = JSON.parse(fs.readFileSync(path.join(mini, 'app.json'), 'utf8'));
const project = JSON.parse(fs.readFileSync(path.join(root, 'project.config.json'), 'utf8'));

function readSource(rel) { return fs.readFileSync(path.join(mini, rel), 'utf8'); }

// ---- 项目结构、语法、BOM、联网规则
assert.equal(project.miniprogramRoot, 'miniprogram/');
assert.deepEqual(app.pages, ['pages/login/login', 'pages/home/home', 'pages/chat/chat', 'pages/handbook/handbook', 'pages/mine/mine',
  'pages/doc/doc', 'pages/article/article', 'pages/history/history']);
assert.ok(!app.tabBar.list.some((tab) => tab.pagePath === 'pages/login/login'), '登录页不应放入底部导航');
assert.equal(app.tabBar.list.find((tab) => tab.pagePath === 'pages/handbook/handbook').text, '知识库');
assert.equal(JSON.parse(readSource('pages/handbook/handbook.json')).navigationBarTitleText, '知识库');
assert.ok(readSource('pages/handbook/handbook.wxml').includes('<view class="page-title">知识库</view>'));
assert.ok(readSource('pages/home/home.wxml').includes('{{suggestionsTitle}}'), '首页常问标题必须随服务端身份变化');
assert.ok(!readSource('pages/home/home.wxml').includes('同学们常问'), '首页不能把所有身份都当成学生');
for (const page of app.pages) {
  for (const ext of ['js', 'json', 'wxml', 'wxss']) assert.ok(fs.existsSync(path.join(mini, page + '.' + ext)), page + '.' + ext);
}
for (const tab of app.tabBar.list) {
  assert.ok(app.pages.includes(tab.pagePath), tab.pagePath);
  // tabBar 图标必须是本地 PNG，缺了开发者工具会直接报错
  for (const key of ['iconPath', 'selectedIconPath']) {
    const file = path.join(mini, tab[key]);
    assert.ok(fs.existsSync(file), '缺少图标 ' + tab[key] + '（运行 python scripts/make-icons.py）');
    assert.equal(fs.readFileSync(file).subarray(1, 4).toString(), 'PNG', tab[key]);
  }
}
const sources = [];
(function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(file);
    else if (/\.(json|js|wxml|wxss)$/.test(file)) sources.push(file);
  }
})(mini);
for (const file of sources) {
  const rel = path.relative(mini, file);
  const buf = fs.readFileSync(file);
  // WXSS/WXML 编译器不认 UTF-8 BOM，会报 unexpected '﻿' at pos 1。
  assert.ok(!(buf[0] === 0xEF && buf[1] === 0xBB && buf[2] === 0xBF), '文件带 UTF-8 BOM（会导致编译失败）：' + rel);
  const code = buf.toString('utf8');
  if (file.endsWith('.json')) JSON.parse(code);
  if (file.endsWith('.js')) {
    new vm.Script(code, { filename: file });
    // 联网只允许出现在 utils/api.js 一处
    if (rel !== path.join('utils', 'api.js')) {
      assert.ok(!/wx\.(request|connectSocket|uploadFile|downloadFile|login)\s*\(/.test(code), '除 utils/api.js 外不得直接联网：' + rel);
    }
  }
}
console.log('PASS 登录入口、八个页面、底部导航图标、JSON 与 JavaScript 语法；联网仅限 utils/api.js');

// ---- 小程序不随包带知识，也不带任何密钥
assert.deepEqual(fs.readdirSync(path.join(mini, 'data')), ['libraries.js'], 'data/ 下只应有知识库注册表');
assert.ok(!fs.existsSync(path.join(mini, 'utils', 'qa.js')), '本地问答已移除：回答只来自后端');
for (const file of sources.filter((item) => /\.(js|wxml)$/.test(item))) {
  const rel = path.relative(mini, file);
  const code = fs.readFileSync(file, 'utf8');
  assert.ok(!/演示资料|课题演示|样例知识|演示身份/.test(code), '不应再出现演示资料字样：' + rel);
  assert.ok(!/sk-[A-Za-z0-9]{16,}|AppSecret\s*[:=]\s*['"][^'"]+['"]/.test(code), '小程序里不得出现密钥：' + rel);
}
// 身份由后端按登录令牌认定，小程序不得自己上报身份
const apiCode = readSource(path.join('utils', 'api.js'));
assert.ok(/Authorization/.test(apiCode) && /\/v1\/auth\/login/.test(apiCode), 'utils/api.js 必须登录并携带令牌');
const mineCode = readSource('pages/mine/mine.js');
assert.ok(!/api\.bindIdentity\s*\(|\b(?:choose|bind|submitCode|codeChange)\s*\(/.test(mineCode), '我的页面不能修改角色');
assert.ok(/api\.signOut\s*\(/.test(mineCode), '我的页面退出必须走统一退出流程');
assert.ok(!/api\.(?:login|ensureLogin)\s*\(/.test(readSource('app.js')), '应用启动不能静默登录');
console.log('PASS 不随包带知识与密钥；身份由后端按令牌认定，问答请求不上报身份');

// ---- 页面：模板里绑定的事件处理函数必须在 js 里定义，否则点了没反应
for (const page of app.pages) {
  const wxml = readSource(page + '.wxml');
  const js = readSource(page + '.js');
  const handlers = new Set();
  wxml.replace(/\b(?:bind|catch)[a-z]*="([A-Za-z_]\w*)"/g, (all, name) => { handlers.add(name); return all; });
  handlers.forEach((name) => assert.ok(new RegExp('\\b' + name + '\\s*\\(').test(js), page + ' 缺少事件处理函数 ' + name));
  // 每个要取数据的页面都要有「连不上 / 加载失败」的出口：
  // 整页状态块（state-title）或问答气泡里的失败提示（answer-failed），并且带一个重试动作
  if (/api\.(catalog|doc|article|history|ask)\(/.test(js)) {
    assert.ok(/state-title|answer-failed/.test(wxml), page + ' 需要加载失败时的提示');
    assert.ok(/bindtap="(load|reload|retry)"/.test(wxml), page + ' 的失败提示需要重试按钮');
  }
}
// 条文签是唯一的引用样式：问答、搜索、文件目录、提问记录都要能点进条文原文
for (const page of ['pages/chat/chat', 'pages/handbook/handbook', 'pages/doc/doc', 'pages/history/history']) {
  assert.ok(/class="slip"[^>]*bindtap="openArticle"/.test(readSource(page + '.wxml')), page + ' 的出处必须能点进条文原文');
}
console.log('PASS 页面事件处理函数齐全；取数据的页面都有失败提示；出处都能点进条文原文');

// ---- 知识库注册表：与后端共用 knowledge_base/data/libraries.json
assert.equal(registry.meta.source, 'knowledge_base/data/libraries.json');
assert.deepEqual(registry.libraries.map((item) => item.id), ['public-guide', 'visitor-guide', 'student-handbook', 'staff-handbook']);
assert.deepEqual(registry.libraries.map((item) => item.name), ['国家教育法规', '杭电游客参观指南', '学生手册', '教职工手册']);
// 游客参观指南只给游客；和教职工手册一样内容待补，没有语料也没接入检索
const visitor = registry.libraries.find((item) => item.id === 'visitor-guide');
assert.deepEqual(visitor.audience, ['guest']);
assert.equal(visitor.content_status, 'pending');
assert.equal(visitor.index_ready, false);
assert.deepEqual(registry.libraries.filter((item) => item.index_ready).map((item) => item.id), ['public-guide', 'student-handbook']);
// 按下标取会随注册表新增条目而错位，这里按 id 取
const publicGuide = registry.libraries.find((item) => item.id === 'public-guide');
const studentHandbook = registry.libraries.find((item) => item.id === 'student-handbook');
assert.deepEqual(publicGuide.doc_index, [1, 3]);
assert.deepEqual(studentHandbook.doc_index, [4, 28]);
assert.equal(publicGuide.documents.length + studentHandbook.documents.length, 28, '两个库合起来是手册的 28 份文件');
assert.ok(!JSON.stringify(registry.libraries).includes('演示'), '注册表里不应再有演示字样');
assert.deepEqual(registry.libraries.filter((item) => item.content_status === 'pending').map((item) => item.id), ['visitor-guide', 'staff-handbook']);
// 用户端只有使用者身份；管理端角色留在注册表里（后端与 kb_admin.py 要用）但不进小程序
assert.deepEqual(store.roles.map((item) => item.identityType), ['guest', 'student', 'teacher']);
assert.deepEqual(registry.identities.filter((item) => item.app === false).map((item) => item.id), ['maintainer', 'reviewer']);
assert.ok(!app.pages.some((page) => page.indexOf('manage') >= 0), '用户端不应有工作台页面');
console.log('PASS 知识库注册表：国家教育法规 3 份 + 学生手册 25 份；用户端只有游客 / 学生 / 教师');

// ---- 本机状态：未登录
store.init();
assert.equal(store.isLoggedIn(), false);
assert.equal(store.identity(), 'guest');
assert.equal(store.role().name, '游客');
assert.equal(store.token(), '');
assert.deepEqual(store.accessibleLibraries().map((item) => item.id), ['public-guide', 'visitor-guide'], '未登录按注册表推算：国家教育法规与游客参观指南');
const device = store.deviceId();
assert.ok(/^mp-/.test(device) && device.length >= 8 && device.length <= 64);
assert.equal(store.deviceId(), device, '设备号生成后保持不变');

function session(identity, extra) {
  return Object.assign({
    user: { id: 'dev-1', identity_type: identity }, identity_type: identity, auth_mode: 'dev',
    binding: { student: 'self', teacher: 'code' },
    libraries: registry.libraries.map((item) => ({ id: item.id, name: item.name, content_status: item.content_status,
      summary: item.summary, accessible: item.audience.indexOf(identity) >= 0 }))
  }, extra || {});
}
// 旧版的静默登录缓存不满足「在登录页选角色并成功登录」。
const legacy = store.read();
legacy.token = 'legacy-token';
legacy.profile = session('student');
delete legacy.loginComplete;
wx.setStorageSync('campus_assistant_v2', legacy);
store.init();
assert.equal(store.isLoggedIn(), false, '旧缓存只有令牌和身份不能跳过登录页');
store.signOut();
store.setSession(session('student', { token: 'partial-token' }));
assert.equal(store.isLoggedIn(), false, '仅刷新身份资料不能标记登录完成');
store.signOut();
store.completeLogin(session('guest', { token: 'guest-token' }));
assert.equal(store.isLoggedIn(), true);
assert.equal(store.read().loginComplete, true);

// ---- 游客对话只在内存里
const question = { id: 'q1', speaker: 'user', text: '对处分不服可以申诉吗' };
const answer = { id: 'a1', speaker: 'assistant', kind: 'answer', question: question.text, feedback: '', citations: [] };
store.appendMessages([question, answer]);
assert.equal(store.getMessages().length, 2);
assert.equal(store.read().messages.length, 0, '游客对话不写入本机存储');
store.updateMessage('a1', { feedback: 'resolved' });
assert.equal(store.getMessages()[1].feedback, 'resolved');
assert.throws(() => store.updateMessage('missing', {}), /已清除/);

// ---- 登录后：身份、知识库来自后端；刷新资料不改变登录状态
store.setSession(session('guest'));
assert.equal(store.token(), 'guest-token');
assert.equal(store.getMessages().length, 2, '身份没变，对话保留');
assert.equal(store.isLoggedIn(), true);
store.signOut();
store.completeLogin(session('student', { token: 'student-token' }));
assert.equal(store.role().name, '学生');
assert.equal(store.getMessages().length, 0, '退出后以学生登录：游客对话失效');
assert.deepEqual(store.accessibleLibraries().map((item) => item.id), ['public-guide', 'student-handbook'], '游客参观指南只给游客');

// ---- 在校身份的对话写入本机，最多 120 条
store.appendMessages([question, answer]);
assert.equal(store.read().messages.length, 2);
store.updateMessage('a1', { feedback: 'unresolved' });
assert.equal(store.read().messages[1].feedback, 'unresolved');
const many = [];
for (let i = 0; i < 130; i++) many.push({ id: 'm' + i, speaker: 'user', text: String(i) });
store.appendMessages(many);
assert.equal(store.getMessages().length, 120);
store.signOut();
store.completeLogin(session('teacher', { token: 'teacher-token' }));
assert.equal(store.getMessages().length, 0, '退出后以教师登录：学生对话已清空');
assert.deepEqual(store.accessibleLibraries().map((item) => item.id), ['public-guide', 'student-handbook', 'staff-handbook']);

// ---- 存储失败要报出来；退出登录清掉令牌与身份、保留设备号
store.appendMessages([question, answer]);
failWrite = true;
assert.throws(() => store.appendMessages([question]), /存储空间不足/);
failWrite = false;
assert.equal(store.getMessages().length, 2, '写入失败时对话不变');
store.clearMessages();
assert.equal(store.getMessages().length, 0);
store.signOut();
assert.equal(store.token(), '');
assert.equal(store.isLoggedIn(), false);
assert.equal(store.identity(), 'guest');
assert.equal(store.deviceId(), device);
console.log('PASS 本机状态：显式登录完成、旧缓存迁移、重新登录清空对话、游客对话不落盘、存储失败提示、退出登录');

// ---- 后端回答 → 页面消息
const generated = api.toMessage({ behavior: 'answer', answer_mode: 'generated', answer: '周日到周四 22:50 熄灯。',
  citations: [{ chunk_id: 'hb-510', doc: '住宿管理规定', article: '第二十二条', page_start: 174, kb: { name: '学生手册' } }],
  suggestions: ['晚归了怎么办？'], session_id: 's1', trace_id: 't1' });
assert.equal(generated.kind, 'answer');
assert.equal(generated.mode, 'generated');
assert.deepEqual(generated.citations[0], { chunkId: 'hb-510', doc: '住宿管理规定', article: '第二十二条', page: 174, kbName: '学生手册' });
const excerpt = api.toMessage({ behavior: 'answer_with_caveat', answer_mode: 'excerpt', degraded: true,
  answer: '条文原文。\n\n出处：《住宿管理规定》第二十二条 第174页\n\n注意：以现行文件为准。', citations: [] });
assert.equal(excerpt.kind, 'answer');
assert.equal(excerpt.degraded, true);
assert.equal(excerpt.text, '条文原文。\n\n注意：以现行文件为准。', '条文原文模式去掉重复的「出处」行，保留时效提示');
assert.equal(api.toMessage({ behavior: 'clarify', answer: '哪方面？' }).kind, 'clarify');
assert.equal(api.toMessage({ behavior: 'refuse_noanswer', answer: '没有依据' }).kind, 'none');
const boundary = api.toMessage({ behavior: 'refuse_boundary', answer: '不代办', boundary: { channel: { note: '请走官方渠道' } } });
assert.equal(boundary.kind, 'boundary');
assert.equal(boundary.note, '请走官方渠道');
console.log('PASS 后端回答到页面消息的映射：整理回答、条文原文、澄清、无依据、越界');

// ---- 认证异步边界：只模拟 wx 回调，不访问真实网络
async function checkAuth() {
  const pending = [];
  const requests = [];
  const navigations = [];
  const state = { globalData: { pendingQuestion: '', pendingDraft: '', pendingCategory: '' } };
  global.getApp = () => state;
  let wxLogins = 0;
  wx.login = ({ success }) => { wxLogins++; success({ code: 'mock-code' }); };
  wx.reLaunch = ({ url, complete }) => { navigations.push(url); if (complete) complete(); };
  wx.request = (options) => { requests.push(options); pending.push(options); };
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  async function take(suffix) {
    for (let i = 0; i < 20 && !pending.length; i++) await tick();
    const req = pending.shift();
    assert.ok(req, '未收到预期请求 ' + suffix);
    assert.ok(req.url.endsWith(suffix), '请求路径不符：' + req.url + '，期望 ' + suffix);
    return req;
  }
  function reply(req, statusCode, data) { req.success({ statusCode, data }); }
  async function finishLogin(identity, code) {
    const result = api.login(identity, code || '');
    const auth = await take('/v1/auth/login');
    reply(auth, 200, session('guest', { token: identity + '-token' }));
    const binding = await take('/v1/me/identity');
    assert.equal(binding.data.identity_type, identity);
    assert.equal(binding.header.Authorization, 'Bearer ' + identity + '-token');
    reply(binding, 200, session(identity));
    const outcome = await result;
    assert.equal(outcome.ok, true);
    assert.equal(store.isLoggedIn(), true);
    assert.equal(store.identity(), identity);
  }

  api.signOut();
  const before = requests.length;
  assert.equal(api.requireLogin(), false);
  const unsigned = await api.catalog();
  assert.equal(unsigned.ok, false);
  assert.equal(requests.length, before, '未登录业务请求不能偷偷登录或访问后端');
  assert.equal(wxLogins, 0);
  assert.equal(navigations.at(-1), '/pages/login/login');

  // 后端认证成功但教师身份绑定失败：临时令牌不能变成已登录状态。
  const wrongTeacher = api.login('teacher', 'wrong');
  reply(await take('/v1/auth/login'), 200, session('student', { token: 'temporary-token' }));
  const wrongBinding = await take('/v1/me/identity');
  assert.equal(wrongBinding.data.identity_type, 'teacher');
  assert.equal(wrongBinding.data.code, 'wrong');
  assert.equal(store.isLoggedIn(), false);
  assert.equal(store.token(), '', '认证中间态令牌不能保存');
  reply(wrongBinding, 403, { code: 'BAD_CODE', message: '教师身份口令不正确' });
  assert.equal((await wrongTeacher).ok, false);
  assert.equal(store.isLoggedIn(), false);
  assert.equal(store.token(), '');

  // 登录请求尚未返回时退出：迟到响应不能重新登录，也不能继续绑定。
  const abandoned = api.login('student');
  const delayedAuth = await take('/v1/auth/login');
  api.signOut();
  reply(delayedAuth, 200, session('guest', { token: 'abandoned-token' }));
  assert.equal((await abandoned).ok, false);
  await tick();
  assert.equal(pending.length, 0, '已退出的登录流程不能继续绑定身份');
  assert.equal(store.isLoggedIn(), false);

  // 绑定请求尚未返回时退出：即使服务器成功绑定，本机仍保持退出。
  const interrupted = api.login('student');
  reply(await take('/v1/auth/login'), 200, session('guest', { token: 'interrupted-token' }));
  const delayedBinding = await take('/v1/me/identity');
  api.signOut();
  reply(delayedBinding, 200, session('student'));
  assert.equal((await interrupted).ok, false);
  assert.equal(store.isLoggedIn(), false);
  assert.equal(store.token(), '');

  await finishLogin('guest');
  assert.equal(api.requireLogin(), true);
  const askResult = api.ask('测试问题', '', 'session-1');
  const ask = await take('/v1/ask');
  assert.ok(!('scope' in ask.data) && !('identity_type' in ask.data), '问答不能上报或覆盖身份');
  reply(ask, 200, { behavior: 'clarify', answer: '请补充具体事项', citations: [] });
  assert.equal((await askResult).ok, true);

  // 新会话建立后，旧 /me 成功响应和旧 401 均不能污染或登出新会话。
  const oldMeResult = api.me();
  const oldMe = await take('/v1/me');
  const oldCatalogResult = api.catalog();
  const oldCatalog = await take('/v1/handbook/catalog');
  api.signOut();
  await finishLogin('student');
  const newerToken = store.token();
  const navCount = navigations.length;
  reply(oldMe, 200, session('guest'));
  reply(oldCatalog, 401, { code: 'TOKEN_INVALID', message: '登录已失效' });
  assert.equal((await oldMeResult).ok, false);
  assert.equal((await oldCatalogResult).ok, false);
  assert.equal(store.identity(), 'student');
  assert.equal(store.token(), newerToken);
  assert.equal(store.isLoggedIn(), true);
  assert.equal(navigations.length, navCount, '旧401不能把新会话送回登录页');

  // 当前令牌失效：清会话回登录，不自动重新获取令牌。
  state.globalData.pendingQuestion = '旧问题';
  state.globalData.pendingDraft = '旧草稿';
  state.globalData.pendingCategory = '校园生活';
  const expired = api.catalog();
  const current = await take('/v1/handbook/catalog');
  const loginCount = wxLogins;
  reply(current, 401, { code: 'TOKEN_INVALID', message: '登录已失效' });
  assert.equal((await expired).ok, false);
  assert.equal(store.isLoggedIn(), false);
  assert.equal(store.token(), '');
  assert.equal(navigations.at(-1), '/pages/login/login');
  assert.equal(wxLogins, loginCount, '401不能静默重新登录');
  assert.ok(!state.globalData.pendingQuestion && !state.globalData.pendingDraft && !state.globalData.pendingCategory);
  await tick();
  assert.equal(pending.length, 0, '过期/退出后不得遗留自动登录请求');
  console.log('PASS 认证边界：未登录拦截、口令失败不落地、退出后丢弃迟到响应、旧401不影响新会话、过期回登录');
}

checkAuth().then(() => console.log('全部本地检查通过。')).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
