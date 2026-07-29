const config = require("./config");
const api = require("./services/api");

App({
  onLaunch() {
    if (!wx.cloud) {
      wx.showModal({ title: "版本过低", content: "请升级微信后再使用本小程序", showCancel: false });
    } else {
      wx.cloud.init({
        env: config.envId || undefined,
        traceUser: true,
      });
    }
  },

  async getSession(force = false) {
    if (!force && this.globalData.session) return this.globalData.session;
    if (!force && this.globalData.sessionPromise) return this.globalData.sessionPromise;
    this.globalData.sessionPromise = api
      .get("/api/v1/session")
      .then((result) => {
        this.globalData.session = result;
        return result;
      })
      .finally(() => {
        this.globalData.sessionPromise = null;
      });
    return this.globalData.sessionPromise;
  },

  globalData: {
    session: null,
    sessionPromise: null,
  },
});
