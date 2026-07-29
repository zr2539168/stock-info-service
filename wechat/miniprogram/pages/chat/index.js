const api = require("../../services/api");
const { dateTime } = require("../../utils/format");

Page({
  data: {
    sessions: [],
    sessionIndex: 0,
    currentSession: null,
    messages: [],
    question: "",
    loading: true,
    sending: false,
    error: "",
  },

  onShow() {
    this.loadSessions();
  },

  async loadSessions() {
    this.setData({ loading: true, error: "" });
    try {
      const result = await api.get("/api/v1/chat/sessions");
      let sessions = result.items || [];
      if (!sessions.length) {
        sessions = [await api.post("/api/v1/chat/sessions")];
      }
      const index = Math.min(this.data.sessionIndex, sessions.length - 1);
      this.setData({ sessions, sessionIndex: index, currentSession: sessions[index] });
      await this.loadMessages();
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  async loadMessages() {
    if (!this.data.currentSession) return;
    const result = await api.get(`/api/v1/chat/sessions/${this.data.currentSession.id}/messages`);
    const messages = (result.items || []).map((item) => ({ ...item, timeText: dateTime(item.created_at) }));
    this.setData({ messages, loading: false });
    wx.nextTick(() => this.setData({ scrollIntoView: messages.length ? `message-${messages[messages.length - 1].id}` : "" }));
  },

  async selectSession(event) {
    const sessionIndex = Number(event.detail.value);
    this.setData({ sessionIndex, currentSession: this.data.sessions[sessionIndex], loading: true });
    await this.loadMessages();
  },

  inputQuestion(event) {
    this.setData({ question: event.detail.value });
  },

  async send() {
    const question = this.data.question.trim();
    if (!question || this.data.sending) return;
    this.setData({ sending: true, question: "", error: "" });
    try {
      await api.post(`/api/v1/chat/sessions/${this.data.currentSession.id}/messages`, { question });
      await this.loadSessions();
    } catch (error) {
      this.setData({ error: error.message, question });
    } finally {
      this.setData({ sending: false });
    }
  },

  async newSession() {
    try {
      const item = await api.post("/api/v1/chat/sessions");
      this.setData({ sessionIndex: 0, currentSession: item });
      await this.loadSessions();
    } catch (error) {
      this.setData({ error: error.message });
    }
  },

  deleteSession() {
    if (!this.data.currentSession) return;
    wx.showModal({
      title: "删除对话",
      content: "此操作会删除本次对话的全部消息。",
      success: async (result) => {
        if (!result.confirm) return;
        await api.delete(`/api/v1/chat/sessions/${this.data.currentSession.id}`);
        this.setData({ sessionIndex: 0 });
        await this.loadSessions();
      },
    });
  },
});
