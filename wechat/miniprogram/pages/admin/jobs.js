const api = require("../../services/api");
const { dateTime } = require("../../utils/format");

const jobs = [
  { key: "all", label: "抓取全部" },
  { key: "quotes", label: "行情" },
  { key: "details", label: "详细交易" },
  { key: "news", label: "新闻" },
  { key: "announcements", label: "公告" },
  { key: "macro", label: "宏观" },
  { key: "indices", label: "指数" },
];

Page({
  data: {
    jobs,
    items: [],
    collectionEnabled: true,
    collectionCron: "0 * * * *",
    loading: true,
    running: false,
    error: "",
  },

  onShow() {
    this.load();
  },

  onHide() {
    this.stopPolling();
  },

  onUnload() {
    this.stopPolling();
  },

  async load() {
    try {
      const [jobResult, settings] = await Promise.all([
        api.get("/api/v1/admin/jobs?limit=50"),
        api.get("/api/v1/admin/settings"),
      ]);
      const items = (jobResult.items || []).map((item) => ({
        ...item,
        startedText: dateTime(item.started_at),
        endedText: dateTime(item.ended_at),
      }));
      const running = items.some((item) => item.status === "running");
      this.setData({
        items,
        collectionEnabled: settings.collection_enabled,
        collectionCron: settings.collect_all_cron,
        running,
        loading: false,
        error: "",
      });
      if (running) this.startPolling();
      else this.stopPolling();
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  async run(event) {
    if (this.data.running) return;
    try {
      await api.post(`/api/v1/admin/jobs/${event.currentTarget.dataset.job}`);
      this.setData({ running: true });
      this.startPolling();
      await this.load();
    } catch (error) {
      this.setData({ error: error.message });
    }
  },

  async toggleCollection(event) {
    try {
      await api.put("/api/v1/admin/settings", {
        collection_enabled: event.detail.value,
        collect_all_cron: this.data.collectionCron,
      });
      this.setData({ collectionEnabled: event.detail.value });
    } catch (error) {
      this.setData({ error: error.message });
    }
  },

  inputCron(event) {
    this.setData({ collectionCron: event.detail.value });
  },

  async saveSchedule() {
    try {
      await api.put("/api/v1/admin/settings", {
        collection_enabled: this.data.collectionEnabled,
        collect_all_cron: this.data.collectionCron,
      });
      wx.showToast({ title: "采集计划已保存" });
    } catch (error) {
      this.setData({ error: error.message });
    }
  },

  startPolling() {
    if (this.pollTimer) return;
    this.pollTimer = setInterval(() => this.load(), 2500);
  },

  stopPolling() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = null;
  },
});
