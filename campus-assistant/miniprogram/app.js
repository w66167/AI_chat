const store = require('./utils/store');
const api = require('./utils/api');

App({
  // pendingQuestion：从首页 / 手册带到问答页、进页面就发出去的问题
  // pendingDraft：带到问答页、只填进输入框等用户改的草稿
  // pendingCategory：从首页带到手册页的分类
  globalData: { pendingQuestion: '', pendingDraft: '', pendingCategory: '' },
  onLaunch() {
    store.init();
    // 启动即静默登录并刷新身份；失败不打扰用户，各页面自己会显示「连不上服务」
    api.ensureLogin().then((res) => { if (res.ok) api.me(); });
  }
});
