from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import AlertRule, MarketQuote, NewsItem


def should_trigger(rule: AlertRule, quote: MarketQuote | None, news: list[NewsItem] | None = None) -> bool:
    if not rule.enabled:
        return False
    if rule.last_triggered_at and datetime.now(timezone.utc) - rule.last_triggered_at < timedelta(minutes=rule.cooldown_minutes):
        return False
    if rule.rule_type == "price_above":
        return quote is not None and quote.price is not None and rule.threshold is not None and quote.price >= rule.threshold
    if rule.rule_type == "price_below":
        return quote is not None and quote.price is not None and rule.threshold is not None and quote.price <= rule.threshold
    if rule.rule_type == "pct_change_above":
        return (
            quote is not None
            and quote.change_percent is not None
            and rule.threshold is not None
            and quote.change_percent >= rule.threshold
        )
    if rule.rule_type == "volume_above":
        return quote is not None and quote.volume is not None and rule.threshold is not None and quote.volume >= rule.threshold
    if rule.rule_type == "keyword":
        keyword = (rule.keyword or "").strip().lower()
        if not keyword:
            return False
        return any(keyword in f"{item.title} {item.summary}".lower() for item in news or [])
    return False


def alert_message(rule: AlertRule, quote: MarketQuote | None) -> str:
    price = "未知" if quote is None or quote.price is None else f"{quote.price:.3f}"
    pct = "未知" if quote is None or quote.change_percent is None else f"{quote.change_percent:.2f}%"
    if rule.rule_type == "keyword":
        return f"提醒「{rule.name or rule.keyword}」触发：匹配到关键词 {rule.keyword}。"
    return f"提醒「{rule.name or rule.rule_type}」触发：当前价格 {price}，涨跌幅 {pct}。"

