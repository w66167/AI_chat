const store = require('../../utils/store');
Page({
  data: { role: store.role(), stats: {}, libraries: [], isGuest: false },
  onShow() { this.refresh(); },
  refresh() {
    const role = store.role();
    this.setData({
      role,
      stats: store.stats(),
      isGuest: !role.history,
      // 每个身份能看到哪些知识库、以及每个知识库的建设状态，都摆在「我的」页里
      libraries: store.getLibraries()
    });
  },
  switchRole() {
    wx.showActionSheet({ itemList: store.roles.map((role) => role.name + (role.id === this.data.role.id ? '（当前）' : '')), success: (res) => {
      try { store.setRole(store.roles[res.tapIndex].id); this.refresh(); wx.showToast({ title: '已切换演示身份', icon: 'none' }); }
      catch (error) { wx.showToast({ title: error.message, icon: 'none' }); }
    } });
  },
  openServices() { wx.switchTab({ url: '/pages/services/services' }); },
  about() { wx.showModal({ title: '关于本次演示', content: '校园知答 v0.5\n问答由后端检索《杭州电子科技大学学生手册》（2017 年版，586 条知识）生成，回答附出处与页码；未接入大模型、学校认证或业务系统。个人事项查询请走学校官方渠道。服务不可用时自动回退到本机 22 条示例知识（分属三个知识库）。身份（游客 / 学生 / 教师、行政人员）决定可查哪些知识库；知识维护与审核由管理端工具完成，不在本小程序内。', showCancel: false }); },
  reset() {
    wx.showModal({ title: '恢复演示初始状态？', content: '将删除本机对话、反馈与知识修改，恢复 22 条样例知识（分属三个知识库）。此操作无法撤销。', confirmText: '恢复初始', confirmColor: '#b95e4c', success: (res) => {
      if (res.confirm) {
        try { store.reset(); getApp().globalData.pendingQuestion = ''; this.refresh(); wx.showToast({ title: '已恢复演示数据', icon: 'success' }); }
        catch (error) { wx.showToast({ title: error.message, icon: 'none' }); }
      }
    } });
  }
});
