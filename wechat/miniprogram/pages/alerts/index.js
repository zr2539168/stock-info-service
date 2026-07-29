const api = require("../../services/api");
const { dateTime } = require("../../utils/format");

const ruleTypes = [
  { key: "price_above", name: "价格高于" },
  { key: "price_below", name: "价格低于" },
  { key: "pct_change_above", name: "涨跌幅高于" },
  { key: "volume_above", name: "成交量高于" },
  { key: "keyword", name: "新闻关键词" },
  { key: "ai_brief", name: "AI 个股简报" },
];

Page({
  data: {
    watchlists: [],
    stockIndex: 0,
    ruleTypes,
    ruleTypeIndex: 0,
    rules: [],
    events: [],
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
      const [watchlistResult, alertResult] = await Promise.all([
        api.get("/api/v1/watchlists"),
        api.get("/api/v1/alerts"),
      ]);
      const watchlists = (watchlistResult.items || []).filter((item) => item.active).map((item) => ({
        ...item,
        label: `${item.stock.market} ${item.stock.symbol} ${item.stock.name || ""}`,
      }));
      this.setData({
        watchlists,
        rules: alertResult.rules || [],
        events: (alertResult.events || []).map((item) => ({ ...item, createdText: dateTime(item.created_at) })),
        loading: false,
      });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  selectStock(event) {
    this.setData({ stockIndex: Number(event.detail.value) });
  },

  selectRuleType(event) {
    this.setData({ ruleTypeIndex: Number(event.detail.value) });
  },

  async add(event) {
    if (!this.data.watchlists.length || this.data.saving) return;
    const values = event.detail.value;
    const ruleType = ruleTypes[this.data.ruleTypeIndex].key;
    this.setData({ saving: true, error: "" });
    try {
      await api.post("/api/v1/alerts", {
        stock_id: this.data.watchlists[this.data.stockIndex].stock_id,
        name: values.name,
        rule_type: ruleType,
        threshold: values.threshold === "" ? null : Number(values.threshold),
        keyword: values.keyword,
        push_mode: values.push_mode ? "once" : "cooldown",
        cooldown_minutes: Number(values.cooldown_minutes || 30),
      });
      wx.showToast({ title: "已创建" });
      await this.load();
    } catch (error) {
      this.setData({ error: error.message });
    } finally {
      this.setData({ saving: false });
    }
  },

  async toggle(event) {
    const { id, enabled } = event.currentTarget.dataset;
    try {
      await api.patch(`/api/v1/alerts/${id}`, { enabled: !enabled });
      await this.load();
    } catch (error) {
      this.setData({ error: error.message });
    }
  },

  remove(event) {
    const id = event.currentTarget.dataset.id;
    wx.showModal({
      title: "删除提醒",
      content: "确定删除这条提醒规则吗？",
      success: async (result) => {
        if (!result.confirm) return;
        await api.delete(`/api/v1/alerts/${id}`);
        await this.load();
      },
    });
  },

  openEvent(event) {
    wx.navigateTo({ url: `/pages/alerts/detail?id=${event.currentTarget.dataset.id}` });
  },
});
