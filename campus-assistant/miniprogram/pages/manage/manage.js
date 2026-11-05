const store = require('../../utils/store');

// 知识库清单来自注册表（knowledge_base/data/libraries.json）。
// 维护人员起草时必须指明条目属于哪个知识库——身份可见性由知识库的 audience 决定。
function emptyForm() {
  return { id: '', targetId: '', title: '', category: '后勤', aliases: '', answer: '', steps: '',
    channel: '', source: '课题演示资料 · 自定义办事指南', scope: '', article: '', page: '',
    kbId: store.DEFAULT_KB };
}
const labels = { pending: '待审核', draft: '草稿', rejected: '已退回', approved: '已发布', published: '已发布' };
Page({
  data: { allowed: false, role: {}, tab: 'pending', items: [], editing: false, form: emptyForm(),
    categories: store.categories.slice(1), categoryIndex: 3,
    libraries: [], kbLabels: [], kbIndex: 0 },
  onShow() { this.refresh(); },
  refresh() {
    const role = store.role();
    const libraries = store.getLibraries();
    const items = this.data.tab === 'published' ? store.getKnowledge() : store.getDrafts().filter((item) =>
      this.data.tab === 'draft' ? ['draft', 'rejected'].includes(item.status) : this.data.tab === 'history' ? item.status === 'approved' : item.status === 'pending');
    this.setData({
      role,
      libraries,
      kbLabels: libraries.map((item) => item.name + (item.contentStatus === 'ready' ? '' : '（内容待补）')),
      // 工作台只对知识维护人员与审核员开放；游客、学生、教师都不能进入（需求文档 2.1、FR-01）。
      allowed: !!role.workbench,
      items: items.map((item) => Object.assign({}, item, { statusLabel: labels[item.status], libraryLabel: this.libraryLabel(item) }))
    });
  },
  libraryLabel(item) {
    const library = store.libraryById(item.kbId);
    return library ? library.name : '未指定知识库';
  },
  changeTab(event) { this.setData({ tab: event.currentTarget.dataset.tab }); this.refresh(); },
  newDraft() {
    const form = emptyForm();
    form.scope = (store.libraryById(form.kbId) || {}).scope_text || '';
    this.setData({ form, categoryIndex: 3, kbIndex: 0, editing: true });
    wx.pageScrollTo({ scrollTop: 0, duration: 200 });
  },
  edit(event) {
    const value = event.currentTarget.dataset.id;
    const item = this.data.tab === 'published' ? store.getItem(value) : store.getDrafts().find((d) => d.id === value);
    if (!item) return;
    const published = this.data.tab === 'published';
    const kbId = store.libraryById(item.kbId) ? item.kbId : store.DEFAULT_KB;
    const kbIndex = Math.max(0, this.data.libraries.findIndex((library) => library.id === kbId));
    this.setData({ editing: true, categoryIndex: this.data.categories.indexOf(item.category), kbIndex, form: {
      id: published ? '' : item.id, targetId: published ? item.id : item.targetId,
      title: item.title, category: item.category, aliases: item.aliases.join('，'), answer: item.answer,
      steps: item.steps.join('\n'), channel: item.channel, source: item.source,
      scope: item.scope || (store.libraryById(kbId) || {}).scope_text || '',
      article: item.article || '', page: item.page ? String(item.page) : '', kbId
    } });
    wx.pageScrollTo({ scrollTop: 0, duration: 200 });
  },
  updateField(event) { this.setData({ ['form.' + event.currentTarget.dataset.field]: event.detail.value }); },
  categoryChange(event) {
    const index = Number(event.detail.value);
    this.setData({ categoryIndex: index, 'form.category': this.data.categories[index] });
  },
  kbChange(event) {
    const index = Number(event.detail.value);
    const library = this.data.libraries[index];
    // 适用范围展示文字跟着知识库走，避免两处口径不一致。
    this.setData({ kbIndex: index, 'form.kbId': library.id, 'form.scope': library.scopeText });
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
    wx.showModal({ title: '审核并发布这条知识？', content: '请确认答案、来源、所属知识库与适用范围完整。发布后，问答与办事指南将立即使用本机新版本。', confirmText: '确认发布', success: (res) => {
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
