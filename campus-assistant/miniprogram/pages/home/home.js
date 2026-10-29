const store = require('../../utils/store');
const api = require('../../utils/api');

Page({
  data: {
    online: false,
    knowledgeCount: 0,
    question: '',
    hot: [
      '宿舍几点熄灯？',
      '挂科了还能补考吗？',
      '转专业需要什么条件？',
      '请假要谁批准？'
    ],
    entries: [
      { label: '学籍与成绩', desc: '注册 · 缓考 · 补考', mark: '学', color: 'blue', question: '挂科了还能补考吗？' },
      { label: '毕业与学位', desc: '结业 · 学位 · 论文', mark: '业', color: 'violet', question: '什么情况拿不到学位证？' },
      { label: '纪律与申诉', desc: '处分 · 作弊 · 申诉', mark: '纪', color: 'amber', question: '处分有哪几种？' },
      { label: '奖助与生活', desc: '奖学金 · 住宿 · 医保', mark: '助', color: 'green', question: '优秀学生奖学金什么时候评？' }
    ]
  },

  onShow() {
    // 在线时用后端的真实知识量，离线时回退本地演示条目数
    api.health().then((res) => {
      const ok = res.ok && res.data && res.data.model_loaded;
      this.setData({
        online: !!ok,
        knowledgeCount: ok ? res.data.chunks : store.stats().knowledge
      });
    });
  },

  inputChange(event) { this.setData({ question: event.detail.value }); },

  ask(event) {
    const q = (event.currentTarget.dataset.question || this.data.question || '').trim();
    getApp().globalData.pendingQuestion = q;
    this.setData({ question: '' });
    wx.switchTab({ url: '/pages/chat/chat' });
  },

  openServices() { wx.navigateTo({ url: '/pages/services/services' }); }
});
