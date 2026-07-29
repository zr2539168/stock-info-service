const api = require("../../services/api");
const { dateTime } = require("../../utils/format");

Page({
  data: { items: [], loading: true, subscribing: false, error: "" },

  onShow() {
    this.load();
  },

  async load() {
    this.setData({ loading: true, error: "" });
    try {
      const result = await api.get("/api/v1/notifications?limit=100");
      const labels = { pending: "等待发送", processing: "正在发送", sent: "微信已发送", no_quota: "仅站内", no_template: "模板未配置", failed: "发送失败" };
      this.setData({
        items: (result.items || []).map((item) => ({
          ...item,
          createdText: dateTime(item.created_at),
          statusText: labels[item.status] || item.status,
        })),
        loading: false,
      });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  async subscribe() {
    if (this.data.subscribing) return;
    this.setData({ subscribing: true, error: "" });
    try {
      const templates = await api.get("/api/v1/notifications/templates");
      const pairs = Object.entries(templates).filter(([, templateId]) => templateId);
      if (!pairs.length) throw new Error("管理员尚未配置微信订阅消息模板 ID");
      const result = await wx.requestSubscribeMessage({ tmplIds: pairs.map(([, templateId]) => templateId) });
      await Promise.all(
        pairs.map(([templateType, templateId]) =>
          api.post("/api/v1/notifications/subscriptions", {
            template_type: templateType,
            result: result[templateId] || "reject",
          })
        )
      );
      wx.showToast({ title: "授权结果已保存" });
    } catch (error) {
      this.setData({ error: error.message || String(error) });
    } finally {
      this.setData({ subscribing: false });
    }
  },

  async open(event) {
    const id = event.currentTarget.dataset.id;
    const item = this.data.items.find((value) => value.id === id);
    if (!item) return;
    try {
      if (!item.read_at) await api.post(`/api/v1/notifications/${id}/read`);
      if (item.page_path) wx.navigateTo({ url: item.page_path });
      else await this.load();
    } catch (error) {
      this.setData({ error: error.message });
    }
  },
});
