const store = require('../../utils/store');
const api = require('../../utils/api');

const FOLD_LENGTH = 220;   // 条文原文超过这个长度先折叠

Page({
  data: {
    messages: [],
    input: '',
    scrollTarget: '',
    busy: false,
    asking: '',          // 正在等待回答的问题
    error: '',           // 上一次提问失败的原因
    failedQuestion: '',
    roleName: '游客',
    isGuest: true,
    libraryNames: '',
    starters: [],
    expanded: {}
  },

  onShow() {
    this.refresh();
    this.loadStarters();
    const app = getApp().globalData;
    if (app.pendingDraft) { this.setData({ input: app.pendingDraft }); app.pendingDraft = ''; }
    if (app.pendingQuestion) { const question = app.pendingQuestion; app.pendingQuestion = ''; this.sendQuestion(question); }
  },

  refresh() {
    const role = store.role();
    const messages = store.getMessages();
    this.setData({
      messages,
      roleName: role.name,
      isGuest: role.identityType === 'guest',
      libraryNames: store.accessibleLibraries().map((item) => item.name).join('、'),
      scrollTarget: messages.length ? 'msg-' + messages[messages.length - 1].id : ''
    });
  },

  // 欢迎页的示例问题由后端按身份给：游客拿到的是国家法规能答的问题
  loadStarters() {
    if (this.startersFor === store.identity() && this.data.starters.length) return;
    api.suggestions().then((res) => {
      if (!res.ok) return;
      this.startersFor = store.identity();
      this.refresh();
      this.setData({ starters: res.data.questions.slice(0, 4) });
    });
  },

  inputChange(event) { this.setData({ input: event.detail.value }); },
  send() { this.sendQuestion(this.data.input); },
  askSuggestion(event) { this.sendQuestion(event.currentTarget.dataset.question); },
  retry() { this.sendQuestion(this.data.failedQuestion); },

  sendQuestion(value) {
    const question = String(value || '').trim();
    if (!question || this.data.busy) return;
    if (question.length > 300) return wx.showToast({ title: '问题请控制在 300 字内', icon: 'none' });
    this.setData({ busy: true, asking: question, error: '', failedQuestion: '', input: '', scrollTarget: 'asking' });

    // 消息成对追加（提问 + 回答），所以最后一条是上一轮的回答，带着上一轮的问题
    const messages = store.getMessages();
    const last = messages[messages.length - 1];
    const previous = last && last.kind === 'answer' ? last.question : '';

    api.ask(question, previous, last ? last.sessionId : '').then((res) => {
      if (!res.ok) {
        // 没有本地知识可以顶替：如实说连不上，并保留问题让用户重试
        this.setData({ busy: false, asking: '', error: res.error, failedQuestion: question, scrollTarget: 'error' });
        return;
      }
      const stamp = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
      const answer = api.toMessage(res.data);
      try {
        store.appendMessages([
          { id: store.id('q'), speaker: 'user', text: question, time: stamp },
          Object.assign({ id: store.id('a'), speaker: 'assistant', question, time: stamp, feedback: '',
            folded: answer.mode === 'excerpt' && answer.text.length > FOLD_LENGTH }, answer)
        ]);
      } catch (error) {
        wx.showToast({ title: error.message, icon: 'none' });
      }
      this.setData({ busy: false, asking: '' });
      this.refresh();
    });
  },

  toggleExpand(event) {
    const id = event.currentTarget.dataset.id;
    const expanded = Object.assign({}, this.data.expanded);
    expanded[id] = !expanded[id];
    this.setData({ expanded });
  },

  openArticle(event) {
    wx.navigateTo({ url: '/pages/article/article?id=' + encodeURIComponent(event.currentTarget.dataset.id) });
  },

  feedback(event) {
    const id = event.currentTarget.dataset.id;
    const value = event.currentTarget.dataset.value;
    try {
      store.updateMessage(id, { feedback: value });
    } catch (error) {
      return wx.showToast({ title: error.message, icon: 'none' });
    }
    this.refresh();
    const message = store.getMessages().find((item) => item.id === id);
    api.feedback({
      session_id: message.sessionId || 'local',
      message_id: message.traceId || id,
      resolved: value === 'resolved',
      score: value === 'resolved' ? 5 : 2,
      reason: message.question || '',
      chunk_id: message.citations.length ? message.citations[0].chunkId : null
    });
    wx.showToast({ title: value === 'resolved' ? '已记录，谢谢' : '已记录，会用来改进', icon: 'none' });
  },

  clear() {
    if (!this.data.messages.length) return;
    wx.showModal({
      title: '开始新对话？',
      content: '当前对话会从本机清除。',
      confirmText: '清除',
      success: (res) => {
        if (!res.confirm) return;
        try { store.clearMessages(); } catch (error) { return wx.showToast({ title: error.message, icon: 'none' }); }
        this.setData({ expanded: {}, error: '', failedQuestion: '' });
        this.refresh();
      }
    });
  },

  openMine() { wx.switchTab({ url: '/pages/mine/mine' }); }
});
