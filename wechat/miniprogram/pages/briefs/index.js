const api = require("../../services/api");
const { dateTime } = require("../../utils/format");

Page({
  data: { items: [], loading: true, generating: false, error: "" },

  onShow() {
    this.load();
  },

  async load() {
    this.setData({ loading: true, error: "" });
    try {
      const result = await api.get("/api/v1/briefs?limit=50");
      this.setData({
        items: (result.items || []).map((item) => ({ ...item, generatedText: dateTime(item.generated_at) })),
        loading: false,
      });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  async generate() {
    if (this.data.generating) return;
    this.setData({ generating: true, error: "" });
    try {
      const item = await api.post("/api/v1/briefs", {});
      wx.navigateTo({ url: `/pages/briefs/detail?id=${item.id}` });
    } catch (error) {
      this.setData({ error: error.message });
    } finally {
      this.setData({ generating: false });
    }
  },

  open(event) {
    wx.navigateTo({ url: `/pages/briefs/detail?id=${event.currentTarget.dataset.id}` });
  },
});
