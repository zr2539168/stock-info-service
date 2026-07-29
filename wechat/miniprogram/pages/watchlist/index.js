const api = require("../../services/api");
const { enrichQuote } = require("../../utils/format");

Page({
  data: {
    items: [],
    markets: ["CN", "HK", "US"],
    marketIndex: 0,
    loading: true,
    saving: false,
    error: "",
  },

  onShow() {
    this.load();
  },

  async load() {
    this.setData({ loading: true, error: "" });
    try {
      const result = await api.get("/api/v1/watchlists");
      this.setData({
        items: (result.items || []).map((item) => ({ ...item, quote: enrichQuote(item.quote) })),
        loading: false,
      });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  selectMarket(event) {
    this.setData({ marketIndex: Number(event.detail.value) });
  },

  async add(event) {
    if (this.data.saving) return;
    const values = event.detail.value;
    this.setData({ saving: true, error: "" });
    try {
      await api.post("/api/v1/watchlists", {
        market: this.data.markets[this.data.marketIndex],
        symbol: values.symbol,
        name: values.name,
        tags: values.tags,
      });
      wx.showToast({ title: "已添加" });
      this.setData({ marketIndex: 0 });
      await this.load();
    } catch (error) {
      this.setData({ error: error.message });
    } finally {
      this.setData({ saving: false });
    }
  },

  async toggle(event) {
    const { id, active } = event.currentTarget.dataset;
    await this.updateItem(id, { active: !active });
  },

  async updateItem(id, payload) {
    try {
      await api.patch(`/api/v1/watchlists/${id}`, payload);
      await this.load();
    } catch (error) {
      this.setData({ error: error.message });
    }
  },

  remove(event) {
    const id = event.currentTarget.dataset.id;
    wx.showModal({
      title: "删除自选股",
      content: "只会从你的自选列表移除，不会删除共享行情历史。",
      success: async (result) => {
        if (!result.confirm) return;
        try {
          await api.delete(`/api/v1/watchlists/${id}`);
          await this.load();
        } catch (error) {
          this.setData({ error: error.message });
        }
      },
    });
  },
});
