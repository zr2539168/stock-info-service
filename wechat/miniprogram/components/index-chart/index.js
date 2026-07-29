Component({
  properties: {
    points: {
      type: Array,
      value: [],
      observer() {
        wx.nextTick(() => this.draw());
      },
    },
    height: {
      type: Number,
      value: 190,
    },
    color: {
      type: String,
      value: "#0878d1",
    },
  },

  lifetimes: {
    ready() {
      this.draw();
    },
  },

  methods: {
    draw() {
      this.createSelectorQuery()
        .select("#chart")
        .fields({ node: true, size: true })
        .exec((result) => {
          const info = result && result[0];
          if (!info || !info.node) return;
          const canvas = info.node;
          const context = canvas.getContext("2d");
          const dpr = wx.getWindowInfo ? wx.getWindowInfo().pixelRatio : wx.getSystemInfoSync().pixelRatio;
          const width = info.width;
          const height = this.properties.height;
          canvas.width = width * dpr;
          canvas.height = height * dpr;
          context.scale(dpr, dpr);
          context.clearRect(0, 0, width, height);
          this.drawSeries(context, width, height);
        });
    },

    drawSeries(context, width, height) {
      const source = this.properties.points || [];
      if (!source.length) return;
      const maximum = Math.max(60, Math.floor(width));
      const points = downsample(source, maximum);
      const values = points.map((item) => Number(item.value)).filter(Number.isFinite);
      if (!values.length) return;
      let minimum = Math.min(...values);
      let maximumValue = Math.max(...values);
      if (minimum === maximumValue) {
        minimum -= 1;
        maximumValue += 1;
      }
      const padding = { top: 14, right: 12, bottom: 28, left: 44 };
      const innerWidth = width - padding.left - padding.right;
      const innerHeight = height - padding.top - padding.bottom;
      context.strokeStyle = "#e2e8f0";
      context.lineWidth = 1;
      context.fillStyle = "#7a8795";
      context.font = "10px sans-serif";
      context.textAlign = "right";
      for (let index = 0; index <= 3; index += 1) {
        const y = padding.top + (innerHeight * index) / 3;
        const value = maximumValue - ((maximumValue - minimum) * index) / 3;
        context.beginPath();
        context.moveTo(padding.left, y);
        context.lineTo(width - padding.right, y);
        context.stroke();
        context.fillText(value.toFixed(1), padding.left - 6, y + 3);
      }
      context.strokeStyle = this.properties.color;
      context.lineWidth = 1.8;
      context.lineJoin = "round";
      context.beginPath();
      points.forEach((point, index) => {
        const x = padding.left + (innerWidth * index) / Math.max(points.length - 1, 1);
        const y = padding.top + ((maximumValue - Number(point.value)) / (maximumValue - minimum)) * innerHeight;
        if (index === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      });
      context.stroke();
      context.fillStyle = "#7a8795";
      context.textAlign = "left";
      context.fillText(String(points[0].date || "").slice(0, 10), padding.left, height - 8);
      context.textAlign = "right";
      context.fillText(String(points[points.length - 1].date || "").slice(0, 10), width - padding.right, height - 8);
    },
  },
});

function downsample(items, maximum) {
  if (items.length <= maximum) return items;
  const step = (items.length - 1) / (maximum - 1);
  return Array.from({ length: maximum }, (_, index) => items[Math.round(index * step)]);
}
