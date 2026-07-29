const api = require("../../services/api");
const { dateTime } = require("../../utils/format");

Page({
  data: { id: null, item: null, loading: true, error: "" },

  onLoad(options) {
    this.setData({ id: Number(options.id) });
    this.load();
  },

  async load() {
    try {
      const item = await api.get(`/api/v1/alerts/events/${this.data.id}`);
      this.setData({ item: { ...item, createdText: dateTime(item.created_at) }, loading: false });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },
});
