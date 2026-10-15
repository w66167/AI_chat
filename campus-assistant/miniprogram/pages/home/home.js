const store = require('../../utils/store');
Page({
  data: {
    quickLinks: [
      { label: '校园卡', mark: '卡', color: 'green', question: '校园卡丢了怎么办？', hint: '挂失 · 充值' },
      { label: '图书馆', mark: '书', color: 'blue', question: '图书馆', hint: '借阅 · 开放' },
      { label: '后勤服务', mark: '修', color: 'amber', question: '宿舍漏水怎么报修？', hint: '住宿 · 报修' },
      { label: '教务服务', mark: '学', color: 'purple', question: '在读证明怎么办理？', hint: '证明 · 选课' }
    ],
    questions: ['校园卡丢了怎么办？', '图书馆什么时候开放？', '校园网怎么连接？']
  },
  onShow() { this.setData({ count: store.stats().knowledge }); },
  ask(event) {
    getApp().globalData.pendingQuestion = event.currentTarget.dataset.question || '';
    wx.switchTab({ url: '/pages/chat/chat' });
  },
  openServices() { wx.switchTab({ url: '/pages/services/services' }); }
});
