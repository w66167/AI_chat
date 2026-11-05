const store = require('../../utils/store');
Page({
  data: { role: store.role(), stats: {}, recent: [], canManage: false, isGuest: false, pendingLabel: '' },
  onShow() { this.refresh(); },
  refresh() {
    const role = store.role();
    const stats = store.stats();
    // 游客不提供跨会话个人历史，因此不展示本机最近操作记录。
    const recent = role.history ? store.read().audit.slice(0, 5).map((item) => Object.assign({}, item, { actorName: (store.roleById(item.actor) || {}).name, displayTime: item.time.slice(0, 16).replace('T', ' ') + ' UTC' })) : [];
    this.setData({
      role, stats, recent, canManage: !!role.workbench, isGuest: !role.history,
      // 待审数量只对工作台角色展示，普通身份看不到运营数据。
      pendingLabel: role.workbench ? stats.pending + ' 待审 →' : '需切换角色 →'
    });
  },
  switchRole() {
    wx.showActionSheet({ itemList: store.roles.map((role) => role.name + (role.id === this.data.role.id ? '（当前）' : '')), success: (res) => {
      try { store.setRole(store.roles[res.tapIndex].id); this.refresh(); wx.showToast({ title: '已切换演示身份', icon: 'none' }); }
      catch (error) { wx.showToast({ title: error.message, icon: 'none' }); }
    } });
  },
  openManage() {
    if (!this.data.canManage) return wx.showToast({ title: '请先切换维护或审核角色', icon: 'none' });
    wx.navigateTo({ url: '/pages/manage/manage' });
  },
  openServices() { wx.switchTab({ url: '/pages/services/services' }); },
  about() { wx.showModal({ title: '关于本次演示', content: '校园知答 v0.3\n问答由后端检索《杭州电子科技大学学生手册》（2017 年版，586 条知识）生成，回答附出处与页码；未接入大模型、学校认证或业务系统。个人事项查询请走学校官方渠道。服务不可用时自动回退到本机 22 条示例知识（其中 20 条公开）。身份切换用于演示 2.1 节的角色与适用范围，不代表真实认证。', showCancel: false }); },
  reset() {
    wx.showModal({ title: '恢复演示初始状态？', content: '将删除本机对话、反馈、知识修改及操作记录，恢复 22 条样例知识（其中 20 条公开）和 1 条待审核知识。此操作无法撤销。', confirmText: '恢复初始', confirmColor: '#b95e4c', success: (res) => {
      if (res.confirm) {
        try { store.reset(); getApp().globalData.pendingQuestion = ''; this.refresh(); wx.showToast({ title: '已恢复演示数据', icon: 'success' }); }
        catch (error) { wx.showToast({ title: error.message, icon: 'none' }); }
      }
    } });
  }
});
