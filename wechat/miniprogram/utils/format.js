function dateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = (number) => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function number(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function enrichQuote(quote) {
  if (!quote) return null;
  const percent = Number(quote.change_percent || 0);
  return {
    ...quote,
    priceText: number(quote.price, 3),
    percentText: `${percent >= 0 ? "+" : ""}${number(percent, 2)}%`,
    trendClass: percent > 0 ? "up" : percent < 0 ? "down" : "",
    observedText: dateTime(quote.observed_at),
  };
}

module.exports = { dateTime, number, enrichQuote };
