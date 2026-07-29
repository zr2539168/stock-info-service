Page({
  data: {
    user: null,
    displayName: "",
    loading: true,
    error: "",
  },

  onShow() {
    this.load();
  },

  async load() {
    this.setData({ loading: true, error: "" });
    try {
      const result = await getApp().getSession(true);
      this.setData({ user: result.user, displayName: result.user.display_name || "", loading: false });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  inputName(event) {
    this.setData({ displayName: event.detail.value });
  },

  async saveName() {
    const api = require("../../services/api");
    try {
      await api.patch("/api/v1/session", { display_name: this.data.displayName });
      await getApp().getSession(true);
      wx.showToast({ title: "已保存" });
      this.load();
    } catch (error) {
      this.setData({ error: error.message });
    }
  },

  navigate(event) {
    wx.navigateTo({ url: event.currentTarget.dataset.url });
  },
});
