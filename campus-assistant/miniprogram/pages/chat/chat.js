const store = require('../../utils/store');
const qa = require('../../utils/qa');
Page({
  data: { messages: [], input: '', scrollTarget: '', busy: false, roleName: '学生', starters: ['校园卡丢了怎么办？', '图书馆什么时候开放？', '宿舍漏水怎么报修？'] },
  onShow() {
    this.refresh();
    const question = getApp().globalData.pendingQuestion;
    if (question) { getApp().globalData.pendingQuestion = ''; this.sendQuestion(question); }
  },
  refresh() {
    const messages = store.read().messages;
    this.setData({ messages, roleName: store.role().name, scrollTarget: messages.length ? 'msg-' + messages[messages.length - 1].id : '' });
  },
  inputChange(event) { this.setData({ input: event.detail.value }); },
  send() { this.sendQuestion(this.data.input); },
  askSuggestion(event) { this.sendQuestion(event.currentTarget.dataset.question); },
  sendQuestion(value) {
    const question = String(value || '').trim();
    if (!question || this.data.busy) return;
    if (question.length > 300) return wx.showToast({ title: '请将问题控制在 300 字内', icon: 'none' });
    this.setData({ busy: true });
    try {
      const messages = store.read().messages;
      // 只在上一轮确实命中知识时承接追问；拒答后清除话题关联。
      const last = messages[messages.length - 1];
      const result = qa.answer(question, store.getKnowledge(), last && last.knowledgeId);
      const stamp = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
      store.appendMessages([
        { id: store.id('q'), speaker: 'user', text: question, time: stamp },
        Object.assign({ id: store.id('a'), speaker: 'assistant', question, time: stamp, feedback: '' }, result)
      ]);
      this.setData({ input: '' }); this.refresh();
    } catch (error) { wx.showModal({ title: '暂时无法保存', content: error.message, showCancel: false }); }
    finally { this.setData({ busy: false }); }
  },
  openSource(event) { wx.navigateTo({ url: '/pages/detail/detail?id=' + encodeURIComponent(event.currentTarget.dataset.id) }); },
  feedback(event) {
    try { store.setFeedback(event.currentTarget.dataset.id, event.currentTarget.dataset.value); this.refresh(); wx.showToast({ title: '谢谢你的反馈', icon: 'success' }); }
    catch (error) { wx.showToast({ title: error.message, icon: 'none' }); }
  },
  clear() {
    wx.showModal({ title: '开始新的咨询？', content: '将清除本机当前对话和对应反馈，知识内容会保留。', success: (res) => {
      if (res.confirm) { try { store.clearMessages(); this.refresh(); } catch (error) { wx.showToast({ title: error.message, icon: 'none' }); } }
    } });
  }
});
