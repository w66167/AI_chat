// 小程序页面联调：在 Node 里模拟微信运行环境，把七个页面的真实代码接到真实后端上走一遍。
//
// 这不是替代微信开发者工具（它不渲染界面），而是在提交前确认
// 「页面逻辑 + 接口字段 + 登录与身份 + 失败提示」整条链路是通的。
//
//   node backend/tests/smoke_miniprogram.js
//
// 脚本自己启动一个后端（随机端口、关键词检索、临时数据目录），跑完即关，不需要先启动服务。
// 找不到带 pydantic 的 Python 时，用环境变量 CAMPUS_PYTHON 指定解释器路径。
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..', '..');
const MP = path.join(ROOT, 'campus-assistant', 'miniprogram');
const PORT = 18000 + Math.floor(Math.random() * 1000);
const BASE = 'http://127.0.0.1:' + PORT;

// ---------------------------------------------------------------- 模拟微信运行环境
const storage = {};
const ui = { toasts: [], modals: [], nav: [], clipboard: '' };
let confirmModals = true;      // wx.showModal 默认点「确定」
let network = true;            // 置 false 模拟断网

global.wx = {
  getStorageSync: (k) => (k in storage ? JSON.parse(JSON.stringify(storage[k])) : ''),
  setStorageSync: (k, v) => { storage[k] = JSON.parse(JSON.stringify(v)); },
  login: ({ success }) => success({ code: 'mock-code' }),
  showToast: (o) => ui.toasts.push(o.title),
  showModal: (o) => { ui.modals.push(o.title); if (o.success) o.success({ confirm: confirmModals }); },
  navigateTo: (o) => ui.nav.push(o.url),
  switchTab: (o) => ui.nav.push('tab:' + o.url),
  pageScrollTo: () => {},
  setClipboardData: (o) => { ui.clipboard = o.data; },
  request({ url, method, data, header, success, fail }) {
    if (!network) return setTimeout(() => fail({ errMsg: 'request:fail' }), 0);
    const target = new URL(url.replace(/^http:\/\/127\.0\.0\.1:8000/, BASE));
    const body = data && method !== 'GET' ? JSON.stringify(data) : null;
    const req = http.request({ hostname: target.hostname, port: target.port, path: target.pathname + target.search,
      method: method || 'GET', headers: Object.assign({}, header, body ? { 'Content-Length': Buffer.byteLength(body) } : {}) },
    (res) => {
      let raw = '';
      res.on('data', (c) => { raw += c; });
      res.on('end', () => { let parsed = raw; try { parsed = JSON.parse(raw); } catch (e) { /* 原样返回 */ } success({ statusCode: res.statusCode, data: parsed }); });
    });
    req.on('error', (e) => fail({ errMsg: e.message }));
    if (body) req.write(body);
    req.end();
  }
};

const appInstance = { globalData: null };
global.App = (def) => { Object.assign(appInstance, def); };
global.getApp = () => appInstance;
let lastPage = null;
global.Page = (def) => { lastPage = def; };

// 加载一个页面：返回带 setData 的实例（data 深拷贝，方法绑定到实例）
function mount(name, options) {
  const file = path.join(MP, 'pages', name, name + '.js');
  delete require.cache[require.resolve(file)];
  require(file);
  const page = Object.assign({}, lastPage, { data: JSON.parse(JSON.stringify(lastPage.data)) });
  page.setData = function (patch) { Object.assign(this.data, JSON.parse(JSON.stringify(patch))); };
  if (page.onLoad) page.onLoad(options || {});
  return page;
}
const tap = (dataset) => ({ currentTarget: { dataset: dataset || {} }, detail: {} });
const typed = (value) => ({ detail: { value }, currentTarget: { dataset: {} } });

// 等到条件成立（页面的网络请求是异步的）
async function until(check, label) {
  for (let i = 0; i < 300; i++) {
    if (check()) return;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error('等待超时：' + label);
}

// ---------------------------------------------------------------- 启动后端
function findPython() {
  const candidates = [process.env.CAMPUS_PYTHON, path.join(ROOT, 'knowledge_base', '.venv', 'Scripts', 'python.exe'),
    path.join(ROOT, 'knowledge_base', '.venv', 'bin', 'python'), 'python', 'python3'].filter(Boolean);
  const { spawnSync } = require('node:child_process');
  for (const exe of candidates) {
    const probe = spawnSync(exe, ['-c', 'import pydantic'], { encoding: 'utf8' });
    if (probe.status === 0) return exe;
  }
  throw new Error('找不到带 pydantic 的 Python，请设置环境变量 CAMPUS_PYTHON');
}

async function startBackend() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'campus-smoke-'));
  const boot = [
    'import os, sys',
    'sys.path.insert(0, sys.argv[1])',
    'from app import auth, deps, history',
    'import app.server as server',
    'tmp = sys.argv[2]',
    "auth.reset_for_tests(os.path.join(tmp, 'users.json'), os.path.join(tmp, 'token.key'))",
    "history.reset_for_tests(os.path.join(tmp, 'history.json'))",
    "server.FEEDBACK_LOG = os.path.join(tmp, 'feedback.jsonl')",
    'cfg = deps.get_config()',
    "cfg.secrets = {'teacher_code': 'T-2026'}",          // 不用本机真实密钥：不调大模型、不走微信
    "cfg.data['search'] = {'backend': 'lexical'}",       // 关键词检索，不需要显卡
    'deps.get_retriever()',
    "server.make_server('127.0.0.1', int(sys.argv[3])).serve_forever()"
  ].join('\n');
  const env = Object.assign({}, process.env, { PYTHONUTF8: '1' });
  for (const key of ['CAMPUS_LLM_API_KEY', 'CAMPUS_WECHAT_APPID', 'CAMPUS_WECHAT_SECRET', 'CAMPUS_TEACHER_CODE']) delete env[key];
  const child = spawn(findPython(), ['-c', boot, path.join(ROOT, 'backend'), tmp, String(PORT)], { env, stdio: ['ignore', 'ignore', 'pipe'] });
  let stderr = '';
  child.stderr.on('data', (c) => { stderr += c; });
  for (let i = 0; i < 150; i++) {
    if (child.exitCode !== null) throw new Error('后端启动失败：\n' + stderr.slice(-800));
    const up = await new Promise((resolve) => {
      http.get(BASE + '/v1/health', (res) => { res.resume(); resolve(res.statusCode === 200); }).on('error', () => resolve(false));
    });
    if (up) return { child, tmp };
    await new Promise((r) => setTimeout(r, 100));
  }
  child.kill();
  throw new Error('后端启动超时：\n' + stderr.slice(-800));
}

// ---------------------------------------------------------------- 流程
async function run() {
  const store = require(path.join(MP, 'utils', 'store.js'));
  const api = require(path.join(MP, 'utils', 'api.js'));
  require(path.join(MP, 'app.js'));
  const app = getApp().globalData;

  // 1. 启动：静默登录，身份是游客
  appInstance.onLaunch();
  await until(() => store.token() && store.profile(), '启动登录');
  assert.equal(store.identity(), 'guest');
  assert.equal(store.profile().auth_mode, 'dev');
  console.log('PASS 启动即静默登录，初始身份为游客（后端未配置小程序密钥 → 开发模式）');

  // 2. 首页（游客）：示例问题来自后端，只列国家法规，提示还有 25 份文件要绑定身份
  const home = mount('home');
  home.onShow();
  await until(() => !home.data.loading, '首页加载');
  assert.equal(home.data.offline, false);
  assert.equal(home.data.isGuest, true);
  assert.equal(home.data.libraryNames, '国家教育法规');
  assert.deepEqual(home.data.categories, [{ name: '国家法规', count: 3 }]);
  assert.equal(home.data.hidden, 25);
  assert.ok(home.data.questions.length >= 3);
  console.log('PASS 首页（游客）：可查国家教育法规 3 份，另有 25 份校内规章提示绑定身份');

  // 3. 游客问校内规章 → 没有依据；问国家法规 → 作答并带出处
  const chat = mount('chat');
  app.pendingQuestion = '宿舍几点熄灯';       // 从首页带过来的问题，进页面自动发出
  chat.onShow();
  await until(() => !chat.data.busy && chat.data.messages.length === 2, '游客提问 1');
  assert.equal(chat.data.messages[1].kind, 'none');
  assert.equal(chat.data.messages[1].citations.length, 0);
  assert.ok(!JSON.stringify(chat.data.messages).includes('住宿'), '不向游客透露校内规章内容');
  chat.sendQuestion(home.data.questions[0]);
  await until(() => !chat.data.busy && chat.data.messages.length === 4, '游客提问 2');
  const guestAnswer = chat.data.messages[3];
  assert.equal(guestAnswer.kind, 'answer');
  assert.ok(guestAnswer.citations.length >= 1);
  assert.ok(guestAnswer.citations.every((c) => c.kbName === '国家教育法规'));
  assert.equal(store.read().messages.length, 0, '游客对话不写入本机存储');
  console.log('PASS 问答（游客）：校内规章查不到且不泄露；国家法规能答并带出处；对话不落盘');

  // 4. 游客打不开校内规章的条文，也看不了提问记录
  const blocked = mount('article', { id: 'hb-510' });
  await until(() => !blocked.data.loading, '受限条文');
  assert.ok(blocked.data.error && !blocked.data.item);
  const guestHistory = mount('history');
  guestHistory.onShow();
  await until(() => !guestHistory.data.loading, '游客提问记录');
  assert.equal(guestHistory.data.needIdentity, true);
  console.log('PASS 游客打不开校内规章条文；提问记录页提示先绑定身份');

  // 5. 我的：绑定学生身份 → 可查范围扩大，原来的游客对话清空
  const mine = mount('mine');
  mine.onShow();
  await until(() => mine.data.signedIn, '我的页加载');
  assert.equal(mine.data.devMode, true);
  assert.equal(mine.data.teacherNeedsCode, true);
  assert.deepEqual(mine.data.options.map((o) => o.identityType), ['student', 'teacher']);
  mine.choose(tap({ identity: 'student' }));
  await until(() => store.identity() === 'student' && !mine.data.binding, '绑定学生');
  assert.equal(mine.data.role.name, '学生');
  assert.deepEqual(mine.data.libraries.filter((l) => l.accessible).map((l) => l.name), ['国家教育法规', '学生手册']);
  assert.equal(store.getMessages().length, 0);
  console.log('PASS 我的：绑定学生身份后可查国家教育法规 + 学生手册，游客对话已清空');

  // 6. 学生提问 → 命中住宿规定第二十二条；点出处进条文原文；翻页；复制；带草稿回问答
  chat.onShow();
  await until(() => chat.data.roleName === '学生' && chat.data.starters.length > 0, '问答页刷新身份');
  chat.sendQuestion('宿舍几点熄灯');
  await until(() => !chat.data.busy && chat.data.messages.length === 2, '学生提问');
  const answer = chat.data.messages[1];
  assert.equal(answer.kind, 'answer');
  assert.equal(answer.mode, 'excerpt', '后端没配模型密钥时给条文原文');
  assert.equal(answer.citations[0].chunkId, 'hb-510');
  assert.ok(!/\n\n出处：/.test(answer.text));
  assert.equal(store.read().messages.length, 2, '在校身份的对话写入本机');
  chat.openArticle(tap({ id: answer.citations[0].chunkId }));
  assert.equal(ui.nav.pop(), '/pages/article/article?id=hb-510');
  const article = mount('article', { id: 'hb-510' });
  await until(() => !article.data.loading, '条文原文');
  assert.equal(article.data.item.article, '第二十二条');
  assert.equal(article.data.item.page_start, 174);
  assert.ok(article.data.item.text.includes('熄灯'));
  article.copy();
  assert.ok(ui.clipboard.includes('熄灯') && ui.clipboard.includes('第二十二条'));
  article.turn(tap({ id: article.data.item.next.id }));
  await until(() => !article.data.loading && article.data.item.id === 'hb-511', '下一条');
  article.ask();
  assert.equal(ui.nav.pop(), 'tab:/pages/chat/chat');
  assert.ok(app.pendingDraft.includes('第二十三条'));
  chat.onShow();
  assert.ok(chat.data.input.includes('第二十三条'), '草稿只填进输入框，不自动发送');
  assert.equal(chat.data.messages.length, 2);
  console.log('PASS 问答（学生）：命中住宿规定第二十二条 → 点出处看原文 → 翻到下一条 → 复制 → 带草稿回问答');

  // 7. 追问带上一轮问题；口语问法；越界与澄清
  chat.setData({ input: '' });
  // 后端这里没配大模型，口语短问法「挂科了还能补考吗」会被保守地拒掉（见 test_service.py），
  // 所以用手册用词来问；口语问法由模型把关的路径在后端测试里覆盖。
  chat.sendQuestion('课程不及格怎么补考？');
  await until(() => !chat.data.busy && chat.data.messages.length === 4, '补考规定');
  assert.equal(chat.data.messages[3].kind, 'answer');
  assert.ok(chat.data.messages[3].citations.some((c) => c.chunkId === 'hb-142'));
  chat.sendQuestion('帮我报修一下宿舍漏水');
  await until(() => !chat.data.busy && chat.data.messages.length === 6, '越界');
  assert.equal(chat.data.messages[5].kind, 'boundary');
  assert.ok(chat.data.messages[5].note);
  chat.sendQuestion('奖学金');
  await until(() => !chat.data.busy && chat.data.messages.length === 8, '澄清');
  assert.equal(chat.data.messages[7].kind, 'clarify');
  assert.ok(chat.data.messages[7].suggestions.length > 0);
  chat.feedback(tap({ id: chat.data.messages[3].id, value: 'resolved' }));
  assert.equal(chat.data.messages[3].feedback, 'resolved');
  console.log('PASS 问答：补考问题命中学籍规定第二十二条；代办请求被拒并给途径；只说「奖学金」时先澄清；反馈已记录');

  // 8. 手册：目录 28 份 7 类、从首页带分类、搜索、打开文件
  const handbook = mount('handbook');
  app.pendingCategory = '校园生活';
  handbook.onShow();
  await until(() => !handbook.data.loading, '手册目录');
  assert.equal(handbook.data.visible, 28);
  assert.equal(handbook.data.hidden, 0);
  assert.equal(handbook.data.categories.length, 8);
  assert.equal(handbook.data.category, '校园生活');
  handbook.keywordChange(typed('熄灯'));
  handbook.search();
  await until(() => handbook.data.searched === '熄灯', '条文搜索');
  assert.equal(handbook.data.results[0].id, 'hb-510');
  handbook.keywordChange(typed('量子纠缠'));
  handbook.search();
  await until(() => handbook.data.searched === '量子纠缠', '无结果搜索');
  assert.equal(handbook.data.results.length, 0);
  handbook.askInstead();
  assert.equal(app.pendingQuestion, '量子纠缠');
  app.pendingQuestion = '';
  handbook.clearSearch();
  handbook.openDoc(tap({ index: 26 }));
  assert.equal(ui.nav.pop(), '/pages/doc/doc?index=26');
  const doc = mount('doc', { index: '26' });
  await until(() => !doc.data.loading, '文件页');
  assert.equal(doc.data.doc.name, '杭州电子科技大学学生住宿管理规定');
  assert.equal(doc.data.chapters.reduce((n, c) => n + c.articles.length, 0), 52);
  console.log('PASS 手册：28 份文件分 7 类、按分类进入、搜索「熄灯」命中第二十二条、搜不到时可转去问答、打开文件看 52 条');

  // 9. 提问记录：服务端保存，能展开、再问、清空
  const history = mount('history');
  history.onShow();
  await until(() => !history.data.loading, '提问记录');
  assert.deepEqual(history.data.items.map((i) => i.question), ['奖学金', '帮我报修一下宿舍漏水', '课程不及格怎么补考？', '宿舍几点熄灯']);
  history.clear();
  await until(() => history.data.items.length === 0, '清空记录');
  console.log('PASS 提问记录：学生的 4 次提问都在服务端，清空后为空');

  // 10. 教师身份要口令：错的拒绝，对的通过；之后解除身份回到游客
  mine.choose(tap({ identity: 'teacher' }));
  assert.equal(mine.data.codeFor, 'teacher', '教师身份先弹口令输入');
  mine.codeChange(typed('wrong'));
  mine.submitCode();
  await until(() => !mine.data.binding && ui.toasts.some((t) => t.includes('口令不正确')), '错误口令');
  assert.equal(store.identity(), 'student');
  mine.codeChange(typed('T-2026'));
  mine.submitCode();
  await until(() => store.identity() === 'teacher' && !mine.data.binding, '绑定教师');
  assert.equal(mine.data.libraries.filter((l) => l.accessible).length, 3);
  mine.choose(tap({ identity: 'guest' }));
  await until(() => store.identity() === 'guest' && !mine.data.binding, '解除身份');
  console.log('PASS 教师身份需要口令（错的拒绝、对的通过）；解除身份后回到游客');

  // 11. 之前打开的受限条文页，回到前台时不能继续显示
  await new Promise((r) => setTimeout(r, 50));
  article.onShow();
  await until(() => !article.data.item, '身份变化后的条文页');
  assert.ok(article.data.error);
  console.log('PASS 身份变成游客后，已打开的校内规章条文页不再显示原文');

  // 12. 断网：各页面给出明确提示和重试，不白屏；问题保留可重发
  network = false;
  chat.onShow();
  chat.sendQuestion('对处分不服怎么申诉');
  await until(() => !chat.data.busy && chat.data.error, '断网提问');
  assert.equal(chat.data.failedQuestion, '对处分不服怎么申诉');
  assert.equal(chat.data.messages.length, 0, '失败的提问不进对话');
  const offlineHome = mount('home');
  offlineHome.onShow();
  await until(() => !offlineHome.data.loading, '断网首页');
  assert.equal(offlineHome.data.offline, true);
  network = true;
  chat.retry();
  await until(() => !chat.data.busy && chat.data.messages.length === 2, '恢复后重试');
  assert.equal(chat.data.error, '');
  assert.equal(chat.data.messages[1].kind, 'answer');
  offlineHome.load();
  await until(() => !offlineHome.data.offline && !offlineHome.data.loading, '恢复后首页');
  console.log('PASS 断网：问答与首页都给出提示和重试；恢复后重发原问题得到回答');

  // 13. 令牌失效：自动重新登录后重试，用户无感
  const db = store.read();
  db.token = 'expired.token.value';
  wx.setStorageSync('campus_assistant_v2', db);
  const res = await api.catalog();
  assert.equal(res.ok, true);
  assert.notEqual(store.token(), 'expired.token.value');
  console.log('PASS 令牌失效时自动重新登录并重试');

  // 14. 退出登录
  mine.signOut();
  await until(() => store.token() && store.identity() === 'guest', '退出后重新建立游客会话');
  assert.equal(store.getMessages().length, 0);
  console.log('PASS 退出登录后清掉本机状态，并以游客身份重新建立会话');
}

(async () => {
  const { child, tmp } = await startBackend();
  let failed = null;
  try { await run(); } catch (error) { failed = error; }
  child.kill();
  try { fs.rmSync(tmp, { recursive: true, force: true }); } catch (e) { /* 临时目录，删不掉也无妨 */ }
  if (failed) { console.error(failed); process.exit(1); }
  console.log('小程序页面联调全部通过（七个页面，真实后端，无需开发者工具）。');
})();
