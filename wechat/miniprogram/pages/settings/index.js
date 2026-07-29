const api = require("../../services/api");

Page({
  data: {
    preference: null,
    models: [],
    modelIndex: 0,
    apiKey: "",
    keyConfigured: false,
    loading: true,
    saving: false,
    testing: false,
    error: "",
  },

  onShow() {
    this.load();
  },

  async load() {
    this.setData({ loading: true, error: "" });
    try {
      const result = await api.get("/api/v1/settings");
      const models = result.allowed_models || [];
      const modelIndex = Math.max(0, models.indexOf(result.preference.deepseek_model));
      this.setData({
        preference: result.preference,
        models,
        modelIndex,
        keyConfigured: result.deepseek_key_configured,
        apiKey: "",
        loading: false,
      });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  inputKey(event) {
    this.setData({ apiKey: event.detail.value });
  },

  selectModel(event) {
    this.setData({ modelIndex: Number(event.detail.value) });
  },

  updatePreference(event) {
    const field = event.currentTarget.dataset.field;
    this.setData({ [`preference.${field}`]: event.detail.value });
  },

  updateTime(event) {
    const field = event.currentTarget.dataset.field;
    this.setData({ [`preference.${field}`]: event.detail.value });
  },

  async save() {
    if (this.data.saving) return;
    this.setData({ saving: true, error: "" });
    try {
      const preference = this.data.preference;
      const payload = {
        deepseek_model: this.data.models[this.data.modelIndex],
        daily_brief_enabled: preference.daily_brief_enabled,
        daily_brief_time: preference.daily_brief_time,
        market_open_briefs_enabled: preference.market_open_briefs_enabled,
        cn_open_brief_time: preference.cn_open_brief_time,
        us_open_brief_time: preference.us_open_brief_time,
      };
      if (this.data.apiKey.trim()) payload.deepseek_api_key = this.data.apiKey.trim();
      await api.put("/api/v1/settings", payload);
      wx.showToast({ title: "设置已保存" });
      await this.load();
    } catch (error) {
      this.setData({ error: error.message });
    } finally {
      this.setData({ saving: false });
    }
  },

  clearKey() {
    wx.showModal({
      title: "清除 DeepSeek Key",
      content: "清除后 AI 对话、简报和指数分析将不可用。",
      success: async (result) => {
        if (!result.confirm) return;
        try {
          await api.put("/api/v1/settings", { clear_deepseek_api_key: true });
          await this.load();
        } catch (error) {
          this.setData({ error: error.message });
        }
      },
    });
  },

  async testKey() {
    if (this.data.testing) return;
    this.setData({ testing: true, error: "" });
    try {
      if (this.data.apiKey.trim()) {
        await api.put("/api/v1/settings", { deepseek_api_key: this.data.apiKey.trim() });
      }
      await api.post("/api/v1/settings/test-deepseek");
      wx.showToast({ title: "连接成功" });
      await this.load();
    } catch (error) {
      this.setData({ error: error.message });
    } finally {
      this.setData({ testing: false });
    }
  },
});
