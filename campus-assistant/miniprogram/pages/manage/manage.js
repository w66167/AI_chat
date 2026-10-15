const store = require('../../utils/store');
function emptyForm() {
  return { id: '', targetId: '', title: '', category: '后勤', aliases: '', answer: '', steps: '',
    channel: '', source: '课题演示资料 · 自定义办事指南', scope: '演示校区 · 公开知识' };
}
const labels = { pending: '待审核', draft: '草稿', rejected: '已退回', approved: '已发布', published: '已发布' };
Page({
  data: { allowed: false, role: {}, tab: 'pending', items: [], editing: false, form: emptyForm(), categories: store.categories.slice(1), categoryIndex: 3 },
  onShow() { this.refresh(); },
  refresh() {
    const role = store.role();
    const items = this.data.tab === 'published' ? store.getKnowledge() : store.getDrafts().filter((item) =>
      this.data.tab === 'draft' ? ['draft', 'rejected'].includes(item.status) : this.data.tab === 'history' ? item.status === 'approved' : item.status === 'pending');
    this.setData({ role, allowed: role.id !== 'student', items: items.map((item) => Object.assign({}, item, { statusLabel: labels[item.status] })) });
  },
  changeTab(event) { this.setData({ tab: event.currentTarget.dataset.tab }); this.refresh(); },
  newDraft() { this.setData({ form: emptyForm(), categoryIndex: 3, editing: true }); wx.pageScrollTo({ scrollTop: 0, duration: 200 }); },
  edit(event) {
    const value = event.currentTarget.dataset.id;
    const item = this.data.tab === 'published' ? store.getItem(value) : store.getDrafts().find((d) => d.id === value);
    if (!item) return;
    const published = this.data.tab === 'published';
    this.setData({ editing: true, categoryIndex: this.data.categories.indexOf(item.category), form: {
      id: published ? '' : item.id, targetId: published ? item.id : item.targetId,
      title: item.title, category: item.category, aliases: item.aliases.join('，'), answer: item.answer,
      steps: item.steps.join('\n'), channel: item.channel, source: item.source, scope: item.scope
    } });
    wx.pageScrollTo({ scrollTop: 0, duration: 200 });
  },
  updateField(event) { this.setData({ ['form.' + event.currentTarget.dataset.field]: event.detail.value }); },
  categoryChange(event) {
    const index = Number(event.detail.value);
    this.setData({ categoryIndex: index, 'form.category': this.data.categories[index] });
  },
  cancel() { this.setData({ editing: false }); },
  save() {
    try {
      store.saveDraft(this.data.form); this.setData({ editing: false, tab: 'draft' }); this.refresh();
      wx.showToast({ title: '草稿已保存', icon: 'success' });
    } catch (error) { this.showError(error); }
  },
  submit(event) {
    try { store.submitDraft(event.currentTarget.dataset.id); this.setData({ tab: 'pending' }); this.refresh(); wx.showToast({ title: '已提交审核', icon: 'success' }); }
    catch (error) { this.showError(error); }
  },
  approve(event) {
    const value = event.currentTarget.dataset.id;
    wx.showModal({ title: '审核并发布这条知识？', content: '请确认答案、来源与适用范围完整。发布后，问答与办事指南将立即使用本机新版本。', confirmText: '确认发布', success: (res) => {
      if (res.confirm) {
        try { store.reviewDraft(value, true); this.refresh(); wx.showToast({ title: '知识已发布', icon: 'success' }); }
        catch (error) { this.showError(error); }
      }
    } });
  },
  reject(event) {
    const value = event.currentTarget.dataset.id;
    wx.showModal({ title: '填写退回原因', editable: true, placeholderText: '例如：请补充清晰的办理步骤', confirmText: '确认退回', success: (res) => {
      if (res.confirm) {
        try { store.reviewDraft(value, false, res.content); this.refresh(); wx.showToast({ title: '已退回修改', icon: 'success' }); }
        catch (error) { this.showError(error); }
      }
    } });
  },
  showError(error) { wx.showModal({ title: '操作未完成', content: error.message, showCancel: false }); },
  toMine() { wx.switchTab({ url: '/pages/mine/mine' }); }
});
