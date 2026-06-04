from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.models import Stock


BEIJING_TZ = ZoneInfo("Asia/Shanghai")
HTML_TAG_RE = re.compile(r"<[^>]+>")
STOCK_ID_RE = re.compile(r"stock_id=([0-9,\s]+)")


def format_beijing_time(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIJING_TZ).strftime(fmt)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = HTML_TAG_RE.sub(" ", text)
    return " ".join(text.split())


def stock_display(stock: Stock | None, fallback: str = "") -> str:
    if stock is None:
        return fallback
    name = f" {stock.name}" if stock.name else ""
    return f"{stock.market} {stock.symbol}{name}"


def replace_stock_refs(value: str | None, stocks: dict[int, Stock] | list[Stock] | tuple[Stock, ...]) -> str:
    if not value:
        return ""
    stock_map = _stock_map(stocks)

    def repl(match: re.Match[str]) -> str:
        ids = [int(part) for part in re.findall(r"\d+", match.group(1))]
        labels = [stock_display(stock_map.get(item_id), f"stock_id={item_id}") for item_id in ids]
        return "、".join(labels)

    return STOCK_ID_RE.sub(repl, value)


def _stock_map(stocks: dict[int, Stock] | list[Stock] | tuple[Stock, ...]) -> dict[int, Stock]:
    if isinstance(stocks, dict):
        return stocks
    return {stock.id: stock for stock in stocks if stock.id is not None}

