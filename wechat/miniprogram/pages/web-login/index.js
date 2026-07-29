const api = require("../../services/api");

Page({
  data: {
    challenge: "",
    user: null,
    confirming: false,
    confirmed: false,
    cancelled: false,
    error: "",
  },

  async onLoad(options) {
    const challenge = options.scene ? decodeURIComponent(options.scene) : options.challenge || "";
    this.setData({ challenge });
    try {
      const session = await getApp().getSession(true);
      this.setData({ user: session.user });
    } catch (error) {
      this.setData({ error: error.message });
    }
  },

  inputChallenge(event) {
    this.setData({ challenge: event.detail.value.trim() });
  },

  async confirm() {
    if (!this.data.challenge || this.data.confirming) return;
    this.setData({ confirming: true, error: "" });
    try {
      await api.post(`/api/v1/admin/web-login/${this.data.challenge}/confirm`);
      this.setData({ confirmed: true });
      wx.showToast({ title: "已确认登录" });
    } catch (error) {
      this.setData({ error: error.message });
    } finally {
      this.setData({ confirming: false });
    }
  },

  async cancel() {
    if (!this.data.challenge || this.data.confirming) return;
    this.setData({ confirming: true, error: "" });
    try {
      await api.post(`/api/v1/admin/web-login/${this.data.challenge}/cancel`);
      this.setData({ cancelled: true });
      wx.showToast({ title: "已取消登录" });
    } catch (error) {
      this.setData({ error: error.message });
    } finally {
      this.setData({ confirming: false });
    }
  },
});
