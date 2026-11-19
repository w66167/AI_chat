const store = require('../../utils/store');
const api = require('../../utils/api');

Page({
  data: {
    roles: store.roles,
    selectedRole: 'student',
    busy: false,
    resuming: false,
    code: '',
    error: ''
  },

  onShow() {
    if (store.isLoggedIn()) this.resumeLogin();
  },

  resumeLogin() {
    if (this.data.busy || !store.isLoggedIn()) return;
    this.setData({ selectedRole: store.identity(), busy: true, resuming: true, error: '' });
    Promise.resolve().then(() => api.me()).then((res) => {
      if (!res.ok) {
        this.setData({ busy: false, resuming: store.isLoggedIn(), error: res.error || '登录验证未完成，请重试。' });
        return;
      }
      this.setData({ selectedRole: store.identity(), busy: false, code: '' });
      wx.switchTab({ url: '/pages/home/home' });
    }).catch((error) => {
      this.setData({ busy: false, resuming: store.isLoggedIn(), error: error.message || '登录验证未完成，请重试。' });
    });
  },

  resetLogin() {
    if (this.data.busy) return;
    api.relogin();
  },

  chooseRole(event) {
    if (this.data.busy || this.data.resuming) return;
    const identity = event.currentTarget.dataset.identity;
    if (!store.roles.some((role) => role.identityType === identity)) return;
    if (identity === this.data.selectedRole) return;
    this.setData({ selectedRole: identity, code: '', error: '' });
  },

  codeChange(event) {
    if (this.data.busy || this.data.resuming) return;
    this.setData({ code: event.detail.value, error: '' });
  },

  submit() {
    if (this.data.busy) return;
    if (store.isLoggedIn()) return this.resumeLogin();
    const identity = this.data.selectedRole;
    if (!store.roles.some((role) => role.identityType === identity)) {
      return this.setData({ error: '请选择登录身份。' });
    }
    const code = identity === 'teacher' ? this.data.code.trim() : '';
    this.setData({ busy: true, error: '' });
    Promise.resolve().then(() => api.login(identity, code)).then((res) => {
      if (!res.ok) {
        this.setData({ busy: false, error: res.error || '登录未完成，请重试。' });
        return;
      }
      this.setData({ busy: false, code: '' });
      wx.switchTab({ url: '/pages/home/home' });
    }).catch((error) => {
      this.setData({ busy: false, error: error.message || '登录未完成，请重试。' });
    });
  }
});
