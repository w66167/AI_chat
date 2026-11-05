const store = require('../../utils/store');
const qa = require('../../utils/qa');
const api = require('../../utils/api');

// 在线优先：后端可用时走真实检索（bge + 重排，579 个知识块），
// 不可用时静默回退到本地演示知识，保证断网/未启动服务时也能演示。
Page({
  data: {
    messages: [],
    input: '',
    scrollTarget: '',
    busy: false,
    loading: false,
    online: false,
    roleName: '学生',
    roleId: 'student',
    isGuest: false,
    kbNotice: '',
    libraryNames: '',
    expanded: {},
    starters: ['宿舍几点熄灯？', '挂科了还能补考吗？', '转专业需要什么条件？']
  },
  onShow() {
    this.refresh();
    this.checkOnline();
    const question = getApp().globalData.pendingQuestion;
    if (question) { getApp().globalData.pendingQuestion = ''; this.sendQuestion(question); }
  },
  checkOnline() {
    api.health().then((res) => {
      const ok = res.ok && res.data && res.data.model_loaded;
      // 上一次回答因为「身份的知识库没接入检索」回退了本机知识时，保持本地徽标，
      // 否则切个 tab 回来徽标又变「在线」，和刚刚那条回答的来源自相矛盾。
      this.setData({ online: !!ok && !this.data.kbNotice });
    });
  },
  refresh() {
    const current = store.role();
    // 游客只读当前匿名会话（内存，不落盘）；登录身份读本机历史。
    const messages = store.getMessages();
    this.setData({
      messages,
      roleName: current.name,
      roleId: current.id,
      isGuest: !current.history,
      // 当前身份能查的知识库：游客只有公开指南，教师会多出教职工手册
      libraryNames: store.librariesFor(current).map((item) => item.name).join(' / '),
      scrollTarget: messages.length ? 'msg-' + messages[messages.length - 1].id : ''
    });
  },
  toMine() { wx.switchTab({ url: '/pages/mine/mine' }); },
  inputChange(event) { this.setData({ input: event.detail.value }); },
  send() { this.sendQuestion(this.data.input); },
  askSuggestion(event) { this.sendQuestion(event.currentTarget.dataset.question); },

  toggleExpand(event) {
    const id = event.currentTarget.dataset.id;
    const expanded = Object.assign({}, this.data.expanded);
    expanded[id] = !expanded[id];
    this.setData({ expanded });
  },

  sendQuestion(value) {
    const question = String(value || '').trim();
    if (!question || this.data.busy) return;
    if (question.length > 300) return wx.showToast({ title: '请将问题控制在 300 字内', icon: 'none' });
    this.setData({ busy: true, loading: true });

    const stamp = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const current = store.role();
    const messages = store.getMessages();
    const last = messages[messages.length - 1];
    // 追问承接：只把上一轮问题带给后端，由后端决定是否使用
    const history = last && last.speaker === 'user' ? [{ question: last.text, answer: '', chunk_id: null }] : [];

    api.ask(question, history, current.identityType).then((res) => {
      if (res.ok && res.data && res.data.kb_gap) {
        // 当前身份对应的知识库还没接入在线检索服务（例如游客的「公开办事指南」）：
        // 回退到本机已发布知识，并说明本次用的是哪个知识库，不拿别的库硬答。
        this.setData({ online: false, kbNotice: res.data.kb_gap_reason || '当前身份对应的知识库尚未接入在线检索，本次改用本机已发布知识回答。' });
        this.append(question, stamp, this.localAnswer(question, last));
        return;
      }
      if (res.ok) {
        this.setData({ online: true, kbNotice: '' });
        this.append(question, stamp, api.toMessage(res.data));
        return;
      }
      // 后端不可用：回退本地演示（按当前身份过滤，范围外有更贴近的条目时兜底）
      this.setData({ online: false });
      this.append(question, stamp, this.localAnswer(question, last));
    }, () => {
      this.append(question, stamp, this.localAnswer(question, last));
    });
  },

  localAnswer(question, last) {
    return qa.answer(question, store.getKnowledge(), last && last.knowledgeId, store.getRestrictedKnowledge());
  },

  append(question, stamp, result) {
    try {
      store.appendMessages([
        { id: store.id('q'), speaker: 'user', text: question, time: stamp },
        Object.assign({ id: store.id('a'), speaker: 'assistant', question, time: stamp, feedback: '' }, result)
      ]);
      this.setData({ input: '', loading: false });
      this.refresh();
    } catch (error) {
      wx.showModal({ title: '暂时无法保存', content: error.message, showCancel: false });
    } finally {
      this.setData({ busy: false, loading: false });
    }
  },

  openSource(event) {
    const id = event.currentTarget.dataset.id;
    if (!id) return;   // 后端知识块不在本地知识库，没有详情页可跳
    wx.navigateTo({ url: '/pages/detail/detail?id=' + encodeURIComponent(id) });
  },

  feedback(event) {
    const id = event.currentTarget.dataset.id;
    const value = event.currentTarget.dataset.value;
    try {
      store.setFeedback(id, value);
      this.refresh();
      wx.showToast({ title: '谢谢你的反馈', icon: 'success' });
      const message = store.getMessages().find((m) => m.id === id);
      if (message && message.remote) {
        api.feedback({
          session_id: api.sessionId(),
          message_id: id,
          resolved: value === 'resolved',
          score: value === 'resolved' ? 5 : 3,
          reason: '',
          chunk_id: null
        });
      }
    } catch (error) {
      wx.showToast({ title: error.message, icon: 'none' });
    }
  },

  clear() {
    wx.showModal({
      title: '开始新的咨询？',
      content: '将清除本机当前对话和对应反馈，知识内容会保留。',
      success: (res) => {
        if (res.confirm) {
          try { store.clearMessages(); this.setData({ expanded: {} }); this.refresh(); api.resetSession(); } catch (error) {
            wx.showToast({ title: error.message, icon: 'none' });
          }
        }
      }
    });
  }
});
