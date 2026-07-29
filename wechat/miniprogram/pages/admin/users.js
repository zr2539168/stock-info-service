const api = require("../../services/api");
const { dateTime } = require("../../utils/format");

Page({
  data: { items: [], loading: true, error: "" },

  onShow() {
    this.load();
  },

  async load() {
    this.setData({ loading: true, error: "" });
    try {
      const result = await api.get("/api/v1/admin/users");
      this.setData({
        items: (result.items || []).map((item) => ({ ...item, createdText: dateTime(item.created_at) })),
        loading: false,
      });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  async setStatus(event) {
    const { id, status, role } = event.currentTarget.dataset;
    try {
      await api.patch(`/api/v1/admin/users/${id}`, { status, role: role || "user" });
      await this.load();
    } catch (error) {
      this.setData({ error: error.message });
    }
  },
});
