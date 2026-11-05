// 小程序端联调的契约测试：用 Node 模拟 wx.request，直接跑 utils/api.js。
// 目的不是替代开发者工具，而是在提交前确认「字段映射 + 失败回退」没写错。
//
//   node backend/tests/smoke_miniprogram.js      （需先启动后端）

const http = require('http');
const path = require('path');

const MP = path.resolve(__dirname, '..', '..', 'campus-assistant', 'miniprogram');
const storage = {};

global.wx = {
  getStorageSync: (k) => storage[k] || '',
  setStorageSync: (k, v) => { storage[k] = v; },
  removeStorageSync: (k) => { delete storage[k]; },
  showToast: () => {},
  showModal: () => {},
  request({ url, method, data, header, timeout, success, fail }) {
    const body = data ? JSON.stringify(data) : null;
    const u = new URL(url);
    const req = http.request({
      hostname: u.hostname, port: u.port, path: u.pathname + u.search,
      method: method || 'GET', timeout: timeout || 8000,
      headers: Object.assign({ 'Content-Type': 'application/json' }, header)
    }, (res) => {
      let raw = '';
      res.on('data', (c) => { raw += c; });
      res.on('end', () => {
        let parsed = raw;
        try { parsed = JSON.parse(raw); } catch (e) { /* 原样返回 */ }
        success && success({ statusCode: res.statusCode, data: parsed });
      });
    });
    req.on('error', (e) => fail && fail({ errMsg: e.message }));
    req.on('timeout', () => { req.destroy(); fail && fail({ errMsg: 'request:fail timeout' }); });
    if (body) req.write(body);
    req.end();
  }
};

const api = require(path.join(MP, 'utils', 'api.js'));
const qa = require(path.join(MP, 'utils', 'qa.js'));
const store = require(path.join(MP, 'utils', 'store.js'));

function show(label, msg) {
  console.log('\n--- %s ---', label);
  console.log('kind=%s behavior=%s conf=%s', msg.kind, msg.behavior || '-', msg.confidence || '-');
  console.log('text: %s', String(msg.text).slice(0, 70).replace(/\n/g, ' '));
  if (msg.libraryName) console.log('知识库: %s %s', msg.libraryName, msg.libraryVersion || '');
  if (msg.source) console.log('文档: %s', msg.source);
  if (msg.article || msg.page) console.log('位置: %s%s', msg.article || '', msg.page ? ' 第' + msg.page + ' 页' : '');
  if (msg.channel) console.log('channel: %s', msg.channel.slice(0, 40));
  if (msg.suggestions.length) console.log('suggestions: %s', msg.suggestions.slice(0, 2).join(' | '));
}

(async () => {
  const h = await api.health();
  console.log('健康检查: ok=%s status=%s model=%s chunks=%s',
    h.ok, h.ok && h.data.status, h.ok && h.data.model, h.ok && h.data.chunks);

  const cases = [
    ['正常作答', '宿舍几点熄灯'],
    ['同义改写', '挂科了还能补考吗'],
    ['无答案', '图书馆几点开门？'],
    ['越权', '帮我报修一下宿舍漏水'],
    ['澄清', '奖学金']
  ];
  // 身份决定能检索哪些知识库：学生可检索学生手册，所以这里传 student
  for (const [label, q] of cases) {
    const res = await api.ask(q, [], 'student');
    if (!res.ok) { console.log('\n--- %s --- 请求失败：%s', label, res.error); continue; }
    const msg = api.toMessage(res.data);
    show(label, msg);
    if (res.data.kb_pending.length) console.log('未接入检索的知识库: %s', res.data.kb_pending.join('、'));
  }

  // 游客的知识库（校园公开办事指南）还没接入检索：服务端应返回 kb_gap，由页面改用本机知识
  console.log('\n--- 游客身份（期望 kb_gap=true）---');
  const guest = await api.ask('宿舍几点熄灯', [], 'guest');
  console.log('ok=%s kb_gap=%s reason=%s',
    guest.ok, guest.ok && guest.data.kb_gap, guest.ok && guest.data.kb_gap_reason);
  console.log('本机回退 kind=%s library=%s text=%s',
    qa.answer('宿舍几点熄灯', store.getKnowledge(), null, store.getRestrictedKnowledge()).kind,
    store.librariesFor(store.role()).map((item) => item.name).join('/'),
    String(qa.answer('宿舍几点熄灯', store.getKnowledge()).text).slice(0, 30));

  // 失败回退：把地址指到死端口，确认页面会退回本地演示
  console.log('\n--- 后端不可用时的回退 ---');
  const original = api.BASE_URL;
  const fallback = qa.answer('校园卡丢了怎么办？', store.getKnowledge(), null, store.getRestrictedKnowledge());
  console.log('本地回退 kind=%s text=%s', fallback.kind, String(fallback.text).slice(0, 40));
  console.log('（api.BASE_URL 保持 %s；失败分支由 chat.js 的 res.ok === false 触发）', original);
})();
