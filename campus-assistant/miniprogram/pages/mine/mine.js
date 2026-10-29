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
  openServices() { wx.navigateTo({ url: '/pages/services/services' }); },
  about() { wx.showModal({ title: '关于本次演示', content: '校园知答 v0.2\n问答由后端检索《杭州电子科技大学学生手册》（2017 年版，586 条知识）生成，回答附出处与页码；未接入大模型、学校认证或业务系统。个人事项查询请走学校官方渠道。服务不可用时自动回退到本机 20 条示例知识。', showCancel: false }); },
  reset() {
    wx.showModal({ title: '恢复演示初始状态？', content: '将删除本机对话、反馈、知识修改及操作记录，恢复 20 条样例知识和 1 条待审核知识。此操作无法撤销。', confirmText: '恢复初始', confirmColor: '#b95e4c', success: (res) => {
      if (res.confirm) {
        try { store.reset(); getApp().globalData.pendingQuestion = ''; this.refresh(); wx.showToast({ title: '已恢复演示数据', icon: 'success' }); }
        catch (error) { wx.showToast({ title: error.message, icon: 'none' }); }
      }
    } });
  }
});
