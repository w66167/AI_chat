const store = require('../../utils/store');
Page({
  data: { role: store.roles[0], stats: {}, recent: [], canManage: false },
  onShow() { this.refresh(); },
  refresh() {
    const role = store.role();
    const recent = store.read().audit.slice(0, 5).map((item) => Object.assign({}, item, { actorName: (store.roles.find((r) => r.id === item.actor) || {}).name, displayTime: item.time.slice(0, 16).replace('T', ' ') + ' UTC' }));
    this.setData({ role, stats: store.stats(), recent, canManage: role.id !== 'student' });
  },
  switchRole() {
    wx.showActionSheet({ itemList: store.roles.map((role) => role.name + (role.id === this.data.role.id ? '（当前）' : '')), success: (res) => {
      try { store.setRole(store.roles[res.tapIndex].id); this.refresh(); wx.showToast({ title: '已切换演示角色', icon: 'none' }); }
      catch (error) { wx.showToast({ title: error.message, icon: 'none' }); }
    } });
  },
  openManage() {
    if (!this.data.canManage) return wx.showToast({ title: '请先切换维护或审核角色', icon: 'none' });
    wx.navigateTo({ url: '/pages/manage/manage' });
  },
  about() { wx.showModal({ title: '关于本次演示', content: '校园知答 v0.1\n本地关键词检索原型，未接入大模型、学校认证或业务系统。资料、身份与窗口名称均用于演示。数据仅保存在当前开发者工具或设备中，不跨设备同步。', showCancel: false }); },
  reset() {
    wx.showModal({ title: '恢复演示初始状态？', content: '将删除本机对话、反馈、知识修改及操作记录，恢复 20 条样例知识和 1 条待审核知识。此操作无法撤销。', confirmText: '恢复初始', confirmColor: '#b95e4c', success: (res) => {
      if (res.confirm) {
        try { store.reset(); getApp().globalData.pendingQuestion = ''; this.refresh(); wx.showToast({ title: '已恢复演示数据', icon: 'success' }); }
        catch (error) { wx.showToast({ title: error.message, icon: 'none' }); }
      }
    } });
  }
});
