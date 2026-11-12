const api = require('../../utils/api');

// 一份文件的条文列表，按章分组。
Page({
  data: { loading: true, error: '', doc: null, chapters: [] },

  onLoad(options) {
    this.index = Number(options.index) || 0;
    this.load();
  },

  load() {
    this.setData({ loading: true, error: '' });
    api.doc(this.index).then((res) => {
      if (!res.ok) return this.setData({ loading: false, error: res.error });
      this.setData({ loading: false, doc: res.data.doc, chapters: res.data.chapters });
    });
  },

  openArticle(event) {
    wx.navigateTo({ url: '/pages/article/article?id=' + encodeURIComponent(event.currentTarget.dataset.id) });
  },

  ask() {
    // 只把文件名填进输入框，让用户接着写想问的事
    getApp().globalData.pendingDraft = '《' + this.data.doc.name + '》里，';
    wx.switchTab({ url: '/pages/chat/chat' });
  }
});
