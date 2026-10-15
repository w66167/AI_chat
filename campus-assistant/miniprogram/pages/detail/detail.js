const store = require('../../utils/store');
Page({
  data: { item: null },
  onLoad(options) { this.itemId = options.id; },
  onShow() { this.setData({ item: store.getItem(this.itemId) || null }); },
  ask() {
    if (!this.data.item) return;
    getApp().globalData.pendingQuestion = this.data.item.title;
    wx.switchTab({ url: '/pages/chat/chat' });
  }
});
