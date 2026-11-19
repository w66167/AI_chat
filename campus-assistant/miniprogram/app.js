const store = require('./utils/store');

App({
  // pendingQuestion：从首页 / 手册带到问答页、进页面就发出去的问题
  // pendingDraft：带到问答页、只填进输入框等用户改的草稿
  // pendingCategory：从首页带到手册页的分类
  globalData: { pendingQuestion: '', pendingDraft: '', pendingCategory: '' },
  onLaunch() {
    store.init();
    // 登录页是入口；由用户选择身份后登录，不在启动时自动创建游客会话。
  }
});
