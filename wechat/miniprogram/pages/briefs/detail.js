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
      const item = await api.get(`/api/v1/briefs/${this.data.id}`);
      this.setData({ item: { ...item, generatedText: dateTime(item.generated_at) }, loading: false });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  remove() {
    wx.showModal({
      title: "删除简报",
      content: "确定删除这份简报吗？",
      success: async (result) => {
        if (!result.confirm) return;
        await api.delete(`/api/v1/briefs/${this.data.id}`);
        wx.navigateBack();
      },
    });
  },
});
