const store = require('../../utils/store');
const api = require('../../utils/api');

Page({
  data: {
    offline: false,
    offlineReason: '',
    role: store.role(),
    isGuest: true,
    signedIn: false,
    devMode: false,
    teacherNeedsCode: false,
    libraries: [],
    options: [],
    binding: false,
    codeFor: '',       // 正在输入口令的身份
    code: ''
  },

  onShow() {
    this.render();
    api.me().then((res) => {
      if (!res.ok) return this.setData({ offline: true, offlineReason: res.error });
      this.setData({ offline: false });
      this.render();
    });
  },

  render() {
    const role = store.role();
    const profile = store.profile();
    this.setData({
      role,
      isGuest: role.identityType === 'guest',
      signedIn: !!(profile && profile.user),
      devMode: !!profile && profile.auth_mode === 'dev',
      teacherNeedsCode: !!profile && (profile.binding || {}).teacher === 'code',
      libraries: store.libraries(),
      // 可以切换到的身份：除当前身份外的另外两种
      options: store.roles.filter((item) => item.identityType !== role.identityType)
    });
  },

  retry() { this.onShow(); },

  choose(event) {
    const identity = event.currentTarget.dataset.identity;
    if (identity === 'teacher' && this.data.teacherNeedsCode) {
      return this.setData({ codeFor: identity, code: '' });
    }
    const target = store.roleByIdentity(identity);
    wx.showModal({
      title: identity === 'guest' ? '解除在校身份？' : '绑定为' + target.name + '？',
      content: identity === 'guest'
        ? '解除后只能查国家教育法规，当前对话会清除。'
        : '身份由你自行声明，用于确定可查的手册范围。切换身份会清除当前对话。',
      confirmText: identity === 'guest' ? '解除' : '绑定',
      success: (res) => { if (res.confirm) this.bind(identity, ''); }
    });
  },

  codeChange(event) { this.setData({ code: event.detail.value }); },
  cancelCode() { this.setData({ codeFor: '', code: '' }); },
  submitCode() {
    if (!this.data.code.trim()) return wx.showToast({ title: '请输入口令', icon: 'none' });
    this.bind(this.data.codeFor, this.data.code.trim());
  },

  bind(identity, code) {
    if (this.data.binding) return;
    this.setData({ binding: true });
    api.bindIdentity(identity, code).then((res) => {
      this.setData({ binding: false });
      if (!res.ok) return wx.showToast({ title: res.error, icon: 'none' });
      this.setData({ codeFor: '', code: '' });
      this.render();
      wx.showToast({ title: identity === 'guest' ? '已解除' : '已绑定为' + store.role().name, icon: 'none' });
    });
  },

  openHistory() { wx.navigateTo({ url: '/pages/history/history' }); },

  about() {
    wx.showModal({
      title: '关于校园知答',
      content: '回答依据《杭州电子科技大学学生手册》（学生处、教务处编，2017 年 9 月版）。回答由大模型根据检索到的条文整理，每条都附出处，可点开核对原文。手册内容与学校文件不符的，以学校文件为准。本服务不查询个人业务数据，也不代办任何业务。',
      showCancel: false,
      confirmText: '知道了'
    });
  },

  signOut() {
    wx.showModal({
      title: '退出登录？',
      content: '本机的登录状态和当前对话会清除。服务端的提问记录保留，重新登录后还能看到。',
      confirmText: '退出',
      success: (res) => {
        if (!res.confirm) return;
        try { store.signOut(); } catch (error) { return wx.showToast({ title: error.message, icon: 'none' }); }
        this.render();
        // 立即以游客身份重新建立会话，各页面才能继续取数据
        api.login().then(() => this.render());
      }
    });
  }
});
