const store = require('../../utils/store');
const api = require('../../utils/api');

Page({
  data: {
    loading: true,
    offline: false,
    offlineReason: '',
    groups: [],
    categories: [],
    category: '全部',
    visible: 0,
    hidden: 0,
    keyword: '',
    searching: false,
    searched: '',
    results: []
  },

  onShow() {
    const app = getApp().globalData;
    const wanted = app.pendingCategory;
    app.pendingCategory = '';
    if (this.loadedFor !== store.identity() || this.data.offline) return this.load(wanted);
    if (wanted) this.setData({ category: wanted, keyword: '', searched: '', results: [] });
  },

  load(wanted) {
    this.setData({ loading: !this.data.groups.length });
    api.catalog().then((res) => {
      if (!res.ok) return this.setData({ loading: false, offline: true, offlineReason: res.error });
      this.loadedFor = store.identity();
      const names = res.data.groups.map((group) => group.category);
      this.setData({
        loading: false,
        offline: false,
        groups: res.data.groups,
        categories: ['全部'].concat(names),
        category: wanted && names.indexOf(wanted) >= 0 ? wanted : '全部',
        visible: res.data.visible,
        hidden: res.data.hidden,
        keyword: '', searched: '', results: []
      });
    });
  },

  reload() { this.load(); },

  changeCategory(event) { this.setData({ category: event.currentTarget.dataset.name }); },

  keywordChange(event) {
    const keyword = event.detail.value;
    this.setData({ keyword });
    if (!keyword.trim()) this.setData({ searched: '', results: [] });
  },

  search() {
    const keyword = this.data.keyword.trim();
    if (!keyword) return;
    this.setData({ searching: true });
    api.search(keyword).then((res) => {
      if (!res.ok) {
        this.setData({ searching: false });
        return wx.showToast({ title: res.error, icon: 'none' });
      }
      this.setData({ searching: false, searched: keyword, results: res.data.items });
    });
  },

  clearSearch() { this.setData({ keyword: '', searched: '', results: [] }); },

  openDoc(event) {
    wx.navigateTo({ url: '/pages/doc/doc?index=' + event.currentTarget.dataset.index });
  },

  openArticle(event) {
    wx.navigateTo({ url: '/pages/article/article?id=' + encodeURIComponent(event.currentTarget.dataset.id) });
  },

  // 条文里搜不到时，把这句话带去问答页问
  askInstead() {
    getApp().globalData.pendingQuestion = this.data.searched;
    wx.switchTab({ url: '/pages/chat/chat' });
  },

  openMine() { wx.switchTab({ url: '/pages/mine/mine' }); }
});
