const api = require("../../services/api");
const { dateTime, number } = require("../../utils/format");

const categories = [
  { key: "news", name: "新闻" },
  { key: "announcements", name: "公告" },
  { key: "macro", name: "宏观" },
  { key: "quotes", name: "行情" },
  { key: "history", name: "历史价格" },
  { key: "trading", name: "交易数据" },
  { key: "order_book", name: "盘口" },
  { key: "institutional", name: "机构资金" },
];

Page({
  data: {
    categories,
    categoryIndex: 0,
    items: [],
    nextCursor: null,
    loading: true,
    error: "",
    isAdmin: false,
  },

  async onShow() {
    try {
      const session = await getApp().getSession();
      this.setData({ isAdmin: session.user.role === "admin" });
    } catch (error) {}
    this.load(true);
  },

  selectCategory(event) {
    this.setData({ categoryIndex: Number(event.detail.value) });
    this.load(true);
  },

  async load(reset = false) {
    if (this.data.loading && !reset) return;
    this.setData({ loading: true, error: "" });
    const category = categories[this.data.categoryIndex];
    const cursor = reset ? null : this.data.nextCursor;
    try {
      const query = cursor ? `?limit=30&cursor=${cursor}` : "?limit=30";
      const result = await api.get(`/api/v1/info/${category.key}${query}`);
      const items = (result.items || []).map((item) => presentItem(category.key, item));
      this.setData({
        items: reset ? items : this.data.items.concat(items),
        nextCursor: result.next_cursor,
        loading: false,
      });
    } catch (error) {
      this.setData({ error: error.message, loading: false });
    }
  },

  loadMore() {
    if (this.data.nextCursor) this.load(false);
  },

  copyLink(event) {
    const url = event.currentTarget.dataset.url;
    if (url) wx.setClipboardData({ data: url });
  },

  remove(event) {
    const id = event.currentTarget.dataset.id;
    const kind = categories[this.data.categoryIndex].key;
    wx.showModal({
      title: "删除共享记录",
      content: "此操作会影响所有用户，确定继续吗？",
      success: async (result) => {
        if (!result.confirm) return;
        try {
          await api.delete(`/api/v1/admin/info/${kind}/${id}`);
          await this.load(true);
        } catch (error) {
          this.setData({ error: error.message });
        }
      },
    });
  },
});

function presentItem(kind, item) {
  const stockText = item.stock ? `${item.stock.market} ${item.stock.symbol} ${item.stock.name || ""}` : "全市场";
  const time = item.published_at || item.observed_at || item.trade_date || item.created_at;
  if (["news", "announcements", "macro"].includes(kind)) {
    return { ...item, displayTitle: item.title, displaySummary: item.summary, stockText, timeText: dateTime(time) };
  }
  if (kind === "history") {
    return {
      ...item,
      displayTitle: `${stockText} · ${String(item.trade_date || "").slice(0, 10)}`,
      displaySummary: `开 ${number(item.open)}  高 ${number(item.high)}  低 ${number(item.low)}  收 ${number(item.close)}`,
      stockText,
      timeText: dateTime(time),
    };
  }
  return {
    ...item,
    displayTitle: stockText,
    displaySummary: `价格 ${number(item.price, 3)} · 涨跌 ${number(item.change_percent)}% · 成交量 ${number(item.volume, 0)}`,
    stockText,
    timeText: dateTime(time),
  };
}
