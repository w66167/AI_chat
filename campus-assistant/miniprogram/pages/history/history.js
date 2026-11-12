const api = require('../../utils/api');

// 提问记录：存在服务端，换设备登录同一个微信也能看到。只有绑定了在校身份的用户有。
Page({
  data: { loading: true, error: '', needIdentity: false, items: [], open: {} },

  onShow() { this.load(); },

  load() {
    this.setData({ loading: !this.data.items.length, error: '' });
    api.history().then((res) => {
      if (!res.ok) {
        return this.setData({ loading: false, items: [], needIdentity: res.code === 'IDENTITY_REQUIRED',
          error: res.code === 'IDENTITY_REQUIRED' ? '' : res.error });
      }
      this.setData({ loading: false, needIdentity: false, items: res.data.items });
    });
  },

  toggle(event) {
    const id = event.currentTarget.dataset.id;
    const open = Object.assign({}, this.data.open);
    open[id] = !open[id];
    this.setData({ open });
  },

  openArticle(event) {
    wx.navigateTo({ url: '/pages/article/article?id=' + encodeURIComponent(event.currentTarget.dataset.id) });
  },

  askAgain(event) {
    getApp().globalData.pendingQuestion = event.currentTarget.dataset.question;
    wx.switchTab({ url: '/pages/chat/chat' });
  },

  clear() {
    wx.showModal({
      title: '清空提问记录？',
      content: '服务端保存的全部提问记录都会删除，无法恢复。',
      confirmText: '清空',
      confirmColor: '#b4432f',
      success: (res) => {
        if (!res.confirm) return;
        api.clearHistory().then((result) => {
          if (!result.ok) return wx.showToast({ title: result.error, icon: 'none' });
          this.setData({ items: [], open: {} });
          wx.showToast({ title: '已清空', icon: 'none' });
        });
      }
    });
  },

  openMine() { wx.switchTab({ url: '/pages/mine/mine' }); },
  openChat() { wx.switchTab({ url: '/pages/chat/chat' }); }
});
