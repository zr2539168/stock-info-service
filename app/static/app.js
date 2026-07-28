document.addEventListener("change", (event) => {
  const target = event.target;
  if (target instanceof HTMLSelectElement && target.dataset.pushModeSelect !== undefined) {
    updateCooldownField(target);
    return;
  }
  if (!(target instanceof HTMLInputElement)) {
    return;
  }
  const selector = target.dataset.selectAll;
  if (!selector) {
    return;
  }
  document.querySelectorAll(selector).forEach((item) => {
    if (item instanceof HTMLInputElement && item.type === "checkbox" && !item.disabled) {
      item.checked = target.checked;
    }
  });
});

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-push-mode-select]").forEach((item) => {
    if (item instanceof HTMLSelectElement) {
      updateCooldownField(item);
    }
  });
  startCollectionButtonPolling();
  initIndexCharts();
});

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.dataset.progress) {
    return;
  }
  if (form.dataset.progressSubmitting === "true") {
    return;
  }

  event.preventDefault();
  form.dataset.progressSubmitting = "true";
  showProgress(form.dataset.progress);
  form.querySelectorAll("button").forEach((control) => {
    if (control instanceof HTMLButtonElement) {
      control.disabled = true;
    }
  });

  try {
    const response = await fetch(form.action, {
      method: form.method || "POST",
      body: new FormData(form),
      headers: { "X-Progress-Request": "1" },
    });
    if (!response.ok) {
      updateProgressJob(`任务请求失败：HTTP ${response.status}`);
      form.dataset.progressSubmitting = "false";
      return;
    }
    const payload = await response.json();
    if (!payload.job_id) {
      window.location.assign(response.url || form.action);
      return;
    }
    pollJobUntilDone(payload.job_id, payload.redirect_url || response.url || form.action);
  } catch (error) {
    updateProgressJob(`任务请求失败：${error instanceof Error ? error.message : String(error)}`);
    form.dataset.progressSubmitting = "false";
  }
});

function showProgress(title) {
  const overlay = document.querySelector("[data-progress-overlay]");
  if (!(overlay instanceof HTMLElement)) {
    return;
  }
  const titleNode = overlay.querySelector("[data-progress-title]");
  const messageNode = overlay.querySelector("[data-progress-message]");
  if (titleNode) {
    titleNode.textContent = title;
  }
  if (messageNode) {
    messageNode.textContent = "正在执行耗时任务，完成后页面会自动更新。";
  }
  updateProgressJob("正在等待后端任务状态...");
  overlay.hidden = false;
}

function pollJobUntilDone(jobId, redirectUrl) {
  let stopped = false;
  const poll = async () => {
    if (stopped) {
      return;
    }
    try {
      const response = await fetch(`/jobs/current?job_id=${encodeURIComponent(jobId)}`, { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const data = await response.json();
      const job = data.job;
      if (!job) {
        updateProgressJob("正在等待后端任务状态...");
        return;
      }
      if (job.status === "running") {
        updateProgressJob(`当前正在执行：${job.label || job.job_name}，开始于 ${job.started_at || "-"}`);
        return;
      }
      if (job.status === "success") {
        stopped = true;
        window.clearInterval(timer);
        updateProgressJob(`任务完成：${job.label || job.job_name}`);
        window.location.assign(redirectUrl);
        return;
      }
      stopped = true;
      window.clearInterval(timer);
      updateProgressJob(`任务失败：${job.error || job.status}`);
    } catch (_error) {
      // Keep the progress UI calm; the main request is still authoritative.
    }
  };
  const timer = window.setInterval(poll, 1200);
  poll();
}

function updateProgressJob(text) {
  const node = document.querySelector("[data-progress-job]");
  if (node) {
    node.textContent = text;
  }
}

function startCollectionButtonPolling() {
  const button = document.querySelector("[data-collection-button]");
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }
  const update = async () => {
    try {
      const response = await fetch("/jobs/current", { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const data = await response.json();
      const running = Array.isArray(data.running) ? data.running : [];
      const collectionRunning = running.some((job) => isCollectionJob(job.job_name));
      button.disabled = collectionRunning;
      button.textContent = collectionRunning ? "后台正在抓取信息" : "手动抓取信息";
    } catch (_error) {
      // The button remains in its last known state if polling fails.
    }
  };
  update();
  window.setInterval(update, 5000);
}

function isCollectionJob(jobName) {
  return [
    "collect_all",
    "manual_all",
    "manual_quotes",
    "manual_details",
    "manual_news",
    "manual_announcements",
    "manual_macro",
    "manual_indices",
  ].includes(jobName);
}

function initIndexCharts() {
  const charts = [];
  document.querySelectorAll("canvas[data-index-chart]").forEach((canvas) => {
    if (!(canvas instanceof HTMLCanvasElement)) {
      return;
    }
    const sourceId = canvas.dataset.indexChart;
    const source = sourceId ? document.getElementById(sourceId) : null;
    if (!source) {
      return;
    }
    let points = [];
    try {
      points = JSON.parse(source.textContent || "[]");
    } catch (_error) {
      points = [];
    }
    const chart = { canvas, points };
    charts.push(chart);
    const render = () => drawIndexChart(canvas, filterIndexPoints(points, selectedIndexRange()));
    render();
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(render).observe(canvas);
    }
  });

  document.querySelectorAll("button[data-index-range]").forEach((button) => {
    button.addEventListener("click", () => {
      const range = button.dataset.indexRange || "1y";
      try {
        window.localStorage.setItem("market-index-range", range);
      } catch (_error) {
        // Local storage is optional; the shared selector still works for this page view.
      }
      updateIndexRangeButtons(range);
      charts.forEach((chart) => drawIndexChart(chart.canvas, filterIndexPoints(chart.points, range)));
    });
  });
  updateIndexRangeButtons(selectedIndexRange());
}

function selectedIndexRange() {
  const allowed = ["7d", "30d", "1y", "10y", "max"];
  try {
    const stored = window.localStorage.getItem("market-index-range");
    return allowed.includes(stored) ? stored : "1y";
  } catch (_error) {
    return "1y";
  }
}

function updateIndexRangeButtons(range) {
  document.querySelectorAll("button[data-index-range]").forEach((button) => {
    const active = button.dataset.indexRange === range;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function filterIndexPoints(points, range) {
  const valid = points.filter((point) => Number.isFinite(Number(point.value)) && point.date);
  if (valid.length === 0 || range === "max") {
    return valid;
  }
  const latest = new Date(`${valid[valid.length - 1].date}T00:00:00Z`);
  const cutoff = new Date(latest);
  if (range === "7d") {
    cutoff.setUTCDate(cutoff.getUTCDate() - 7);
  } else if (range === "30d") {
    cutoff.setUTCMonth(cutoff.getUTCMonth() - 1);
  } else if (range === "10y") {
    cutoff.setUTCFullYear(cutoff.getUTCFullYear() - 10);
  } else {
    cutoff.setUTCFullYear(cutoff.getUTCFullYear() - 1);
  }
  return valid.filter((point) => new Date(`${point.date}T00:00:00Z`) >= cutoff);
}

function drawIndexChart(canvas, points) {
  const width = Math.max(canvas.clientWidth, 280);
  const height = Math.max(canvas.clientHeight, 220);
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);

  const valid = points.filter((point) => Number.isFinite(Number(point.value)));
  if (valid.length === 0) {
    context.fillStyle = "#98a2b3";
    context.font = '13px "Segoe UI", sans-serif';
    context.fillText("暂无历史数据", 16, height / 2);
    return;
  }

  const values = valid.map((point) => Number(point.value));
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  const span = maximum - minimum || Math.max(Math.abs(maximum) * 0.08, 1);
  minimum -= span * 0.1;
  maximum += span * 0.1;

  const padding = { top: 18, right: 18, bottom: 30, left: 48 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const x = (index) => padding.left + (valid.length === 1 ? plotWidth / 2 : (index / (valid.length - 1)) * plotWidth);
  const y = (value) => padding.top + ((maximum - value) / (maximum - minimum)) * plotHeight;

  context.strokeStyle = "#e4e7ec";
  context.fillStyle = "#667085";
  context.font = '11px "Segoe UI", sans-serif';
  context.lineWidth = 1;
  for (let step = 0; step <= 4; step += 1) {
    const gridY = padding.top + (step / 4) * plotHeight;
    context.beginPath();
    context.moveTo(padding.left, gridY);
    context.lineTo(width - padding.right, gridY);
    context.stroke();
    const label = maximum - (step / 4) * (maximum - minimum);
    context.fillText(label.toFixed(1), 6, gridY + 4);
  }

  const gradient = context.createLinearGradient(0, padding.top, 0, height - padding.bottom);
  gradient.addColorStop(0, "rgba(21, 127, 116, 0.22)");
  gradient.addColorStop(1, "rgba(21, 127, 116, 0.01)");
  context.beginPath();
  valid.forEach((point, index) => {
    const method = index === 0 ? "moveTo" : "lineTo";
    context[method](x(index), y(Number(point.value)));
  });
  context.lineTo(x(valid.length - 1), height - padding.bottom);
  context.lineTo(x(0), height - padding.bottom);
  context.closePath();
  context.fillStyle = gradient;
  context.fill();

  context.beginPath();
  valid.forEach((point, index) => {
    const method = index === 0 ? "moveTo" : "lineTo";
    context[method](x(index), y(Number(point.value)));
  });
  context.strokeStyle = "#157f74";
  context.lineWidth = 2;
  context.lineJoin = "round";
  context.stroke();

  const latestIndex = valid.length - 1;
  context.beginPath();
  context.arc(x(latestIndex), y(Number(valid[latestIndex].value)), 3.5, 0, Math.PI * 2);
  context.fillStyle = "#0e5f57";
  context.fill();
  context.fillStyle = "#667085";
  context.fillText(valid[0].date || "", padding.left, height - 8);
  const lastDate = valid[latestIndex].date || "";
  const dateWidth = context.measureText(lastDate).width;
  context.fillText(lastDate, width - padding.right - dateWidth, height - 8);
}

function updateCooldownField(select) {
  const form = select.closest("form");
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  const field = form.querySelector("[data-cooldown-field]");
  const input = field ? field.querySelector("input[name='cooldown_minutes']") : null;
  const isOneTime = select.value === "once";
  if (field instanceof HTMLElement) {
    field.hidden = isOneTime;
  }
  if (input instanceof HTMLInputElement) {
    input.disabled = isOneTime;
    input.required = !isOneTime;
  }
}
