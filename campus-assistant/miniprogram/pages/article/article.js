const api = require('../../utils/api');

// 条文原文。问答里的每条出处、搜索结果、文件目录都通到这里。
Page({
  data: { loading: true, error: '', item: null },

  onLoad(options) {
    this.chunkId = options.id || '';
    this.load();
  },

  // 每次回到这一页都重新取：切了身份之后，无权查看的条文不能继续留在屏幕上
  onShow() { if (this.loaded) this.load(true); },

  load(silent) {
    if (!silent) this.setData({ loading: true, error: '' });
    api.article(this.chunkId).then((res) => {
      this.loaded = true;
      if (!res.ok) return this.setData({ loading: false, error: res.error, item: null });
      this.setData({ loading: false, error: '', item: res.data });
    });
  },

  turn(event) {
    const id = event.currentTarget.dataset.id;
    if (!id) return;
    this.chunkId = id;
    this.load();
    wx.pageScrollTo({ scrollTop: 0, duration: 0 });
  },

  openDoc() {
    wx.navigateTo({ url: '/pages/doc/doc?index=' + this.data.item.doc_index });
  },

  copy() {
    const item = this.data.item;
    wx.setClipboardData({ data: item.text + '\n——' + item.source });
  },

  ask() {
    const item = this.data.item;
    getApp().globalData.pendingDraft = '《' + item.doc + '》' + item.article + '里，';
    wx.switchTab({ url: '/pages/chat/chat' });
  }
});
