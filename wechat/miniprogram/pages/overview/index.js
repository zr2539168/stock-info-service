const api = require("../../services/api");
const { enrichQuote, dateTime } = require("../../utils/format");

Page({
  data: {
    loading: true,
    error: "",
    dashboard: null,
  },

  onShow() {
    this.load();
  },

  async onPullDownRefresh() {
    await this.load();
    wx.stopPullDownRefresh();
  },

  async load() {
    this.setData({ loading: true, error: "" });
    try {
      const session = await getApp().getSession(true);
      if (session.user.status !== "active") {
        this.setData({ loading: false });
        wx.switchTab({ url: "/pages/mine/index" });
        return;
      }
      const result = await api.get("/api/v1/dashboard");
      const dashboard = {
        ...result,
        quotes: (result.quotes || []).map((item) => ({ ...item, quote: enrichQuote(item.quote) })),
        latestBriefTime: result.latest_brief ? dateTime(result.latest_brief.generated_at) : "",
      };
      this.setData({ dashboard, loading: false });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  openBriefs() {
    wx.navigateTo({ url: "/pages/briefs/index" });
  },

  openNotifications() {
    wx.navigateTo({ url: "/pages/notifications/index" });
  },
});
