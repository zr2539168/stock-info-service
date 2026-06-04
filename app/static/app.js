document.addEventListener("change", (event) => {
  const target = event.target;
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
