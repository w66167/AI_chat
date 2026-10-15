const store = require('../../utils/store');
Page({
  data: { categories: store.categories, category: '全部', search: '', items: [] },
  onShow() { this.refresh(); },
  refresh() {
    const keyword = this.data.search.trim().toLowerCase();
    this.setData({ items: store.getKnowledge().filter((item) =>
      (this.data.category === '全部' || item.category === this.data.category) &&
      (!keyword || [item.title, item.answer].concat(item.aliases).join(' ').toLowerCase().includes(keyword))) });
  },
  changeCategory(event) { this.setData({ category: event.currentTarget.dataset.category }); this.refresh(); },
  searchChange(event) { this.setData({ search: event.detail.value }); this.refresh(); },
  open(event) { wx.navigateTo({ url: '/pages/detail/detail?id=' + encodeURIComponent(event.currentTarget.dataset.id) }); }
});
