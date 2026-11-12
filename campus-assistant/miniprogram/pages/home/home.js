const store = require('../../utils/store');
const api = require('../../utils/api');

Page({
  data: {
    loading: true,
    offline: false,
    offlineReason: '',
    roleName: '游客',
    isGuest: true,
    libraryNames: '',
    draft: '',
    questions: [],
    categories: [],
    hidden: 0
  },

  onShow() {
    // 身份没变且已经加载过，就不重复请求
    if (this.loadedFor === store.identity() && !this.data.offline) return this.syncRole();
    this.load();
  },

  syncRole() {
    const role = store.role();
    this.setData({
      roleName: role.name,
      isGuest: role.identityType === 'guest',
      libraryNames: store.accessibleLibraries().map((item) => item.name).join('、')
    });
  },

  load() {
    this.setData({ loading: !this.data.questions.length });
    Promise.all([api.suggestions(), api.catalog()]).then(([suggested, catalog]) => {
      if (!suggested.ok || !catalog.ok) {
        const failed = suggested.ok ? catalog : suggested;
        this.setData({ loading: false, offline: true, offlineReason: failed.error });
        return this.syncRole();
      }
      this.loadedFor = store.identity();
      this.syncRole();
      this.setData({
        loading: false,
        offline: false,
        questions: suggested.data.questions.slice(0, 5),
        categories: catalog.data.groups.map((group) => ({ name: group.category, count: group.docs.length })),
        hidden: catalog.data.hidden
      });
    });
  },

  draftChange(event) { this.setData({ draft: event.detail.value }); },

  submit() {
    const question = this.data.draft.trim();
    if (!question) return wx.switchTab({ url: '/pages/chat/chat' });
    this.setData({ draft: '' });
    this.go(question);
  },

  ask(event) { this.go(event.currentTarget.dataset.question); },

  go(question) {
    getApp().globalData.pendingQuestion = question;
    wx.switchTab({ url: '/pages/chat/chat' });
  },

  openCategory(event) {
    getApp().globalData.pendingCategory = event.currentTarget.dataset.name;
    wx.switchTab({ url: '/pages/handbook/handbook' });
  },

  openHandbook() { wx.switchTab({ url: '/pages/handbook/handbook' }); },
  openMine() { wx.switchTab({ url: '/pages/mine/mine' }); }
});
