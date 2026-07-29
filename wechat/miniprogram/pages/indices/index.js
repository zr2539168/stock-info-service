const api = require("../../services/api");
const { dateTime, number } = require("../../utils/format");

const ranges = [
  { key: "1w", label: "一周" },
  { key: "1m", label: "一月" },
  { key: "1y", label: "一年" },
  { key: "10y", label: "十年" },
  { key: "max", label: "成立以来" },
];

Page({
  data: {
    ranges,
    selectedRange: "1y",
    cards: [],
    analysis: null,
    loading: true,
    analyzing: false,
    error: "",
  },

  onShow() {
    this.load();
  },

  selectRange(event) {
    const selectedRange = event.currentTarget.dataset.range;
    if (selectedRange === this.data.selectedRange) return;
    this.setData({ selectedRange });
    this.load();
  },

  async load() {
    this.setData({ loading: true, error: "" });
    try {
      const result = await api.get(`/api/v1/indices?range=${this.data.selectedRange}`);
      const cards = (result.cards || []).map((card) => {
        const series = card.series || [];
        const latestValue = card.latest ? Number(card.latest.value) : null;
        const previous = series.length > 1 ? Number(series[series.length - 2].value) : null;
        const change = latestValue !== null && previous !== null ? latestValue - previous : null;
        return {
          ...card,
          code: card.definition.code,
          series,
          latestText: latestValue === null ? "-" : number(latestValue, 2),
          changeText: change === null ? "" : `${change >= 0 ? "+" : ""}${number(change, 2)}`,
          trendClass: change > 0 ? "up" : change < 0 ? "down" : "",
          observedText: card.latest ? dateTime(card.latest.observed_at) : "尚未采集",
          sourceText: card.latest ? card.latest.source : card.definition.source,
        };
      });
      this.setData({ cards, analysis: result.analysis, loading: false });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  async analyze() {
    if (this.data.analyzing) return;
    this.setData({ analyzing: true, error: "" });
    try {
      const analysis = await api.post("/api/v1/indices/analyze");
      this.setData({ analysis });
    } catch (error) {
      this.setData({ error: error.message });
    } finally {
      this.setData({ analyzing: false });
    }
  },

  copySource(event) {
    wx.setClipboardData({ data: event.currentTarget.dataset.url });
  },
});
