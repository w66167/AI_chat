const store = require('../../utils/store');
const api = require('../../utils/api');

Page({
  data: {
    offline: false,
    offlineReason: '',
    role: store.role(),
    isGuest: true,
    devMode: false,
    libraries: []
  },

  onShow() {
    if (!api.requireLogin()) return;
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
      devMode: !!profile && profile.auth_mode === 'dev',
      libraries: store.libraries()
    });
  },

  retry() { this.onShow(); },

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
        try { api.signOut(); } catch (error) { wx.showToast({ title: error.message, icon: 'none' }); }
      }
    });
  }
});
