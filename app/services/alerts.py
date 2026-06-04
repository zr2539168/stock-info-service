from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import AlertRule, MarketQuote, NewsItem


def _u(*codepoints: int) -> str:
    return "".join(chr(codepoint) for codepoint in codepoints)


def should_trigger(rule: AlertRule, quote: MarketQuote | None, news: list[NewsItem] | None = None) -> bool:
    if not rule.enabled:
        return False
    if rule.last_triggered_at and datetime.now(timezone.utc) - rule.last_triggered_at < timedelta(minutes=rule.cooldown_minutes):
        return False
    if rule.rule_type == "ai_brief":
        return True
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
    price = _u(0x672A, 0x77E5) if quote is None or quote.price is None else f"{quote.price:.3f}"
    pct = _u(0x672A, 0x77E5) if quote is None or quote.change_percent is None else f"{quote.change_percent:.2f}%"
    if rule.rule_type == "keyword":
        return (
            f"{_u(0x63D0, 0x9192)}{_u(0x300C)}{rule.name or rule.keyword}{_u(0x300D)}"
            f"{_u(0x89E6, 0x53D1, 0xFF1A, 0x5339, 0x914D, 0x5230, 0x5173, 0x952E, 0x8BCD)} {rule.keyword}{_u(0x3002)}"
        )
    if rule.rule_type == "ai_brief":
        name = rule.name or "AI\u7b80\u62a5\u63a8\u9001"
        return f"{_u(0x63D0, 0x9192)}{_u(0x300C)}{name}{_u(0x300D)} AI\u7b80\u62a5\u5df2\u751f\u6210\u5e76\u63a8\u9001\u3002"
    return (
        f"{_u(0x63D0, 0x9192)}{_u(0x300C)}{rule.name or rule.rule_type}{_u(0x300D)}"
        f"{_u(0x89E6, 0x53D1, 0xFF1A, 0x5F53, 0x524D, 0x4EF7, 0x683C)} {price}"
        f"{_u(0xFF0C, 0x6DA8, 0x8DCC, 0x5E45)} {pct}{_u(0x3002)}"
    )
