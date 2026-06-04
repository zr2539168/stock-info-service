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
