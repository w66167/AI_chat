const store = require('./utils/store');

App({
  globalData: { pendingQuestion: '' },
  onLaunch() {
    store.init();
  }
});
