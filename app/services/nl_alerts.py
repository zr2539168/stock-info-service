from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from app.models import Stock
from app.services.ai import AiResult


ALLOWED_RULE_TYPES = {"price_above", "price_below", "pct_change_above", "volume_above", "keyword"}


class JsonAiClient(Protocol):
    async def complete_json(self, system_prompt: str, user_prompt: str) -> AiResult: ...


@dataclass
class NaturalAlertPlan:
    stock_id: int
    name: str
    rule_type: str
    threshold: float | None = None
    keyword: str = ""
    cooldown_minutes: int = 30


@dataclass
class NaturalAlertParseResult:
    ok: bool
    plan: NaturalAlertPlan | None = None
    error: str = ""


async def parse_natural_alert_with_ai(
    text: str,
    stocks: list[Stock],
    ai: JsonAiClient,
    default_cooldown: int = 30,
) -> NaturalAlertParseResult:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return NaturalAlertParseResult(False, error="Empty alert description")
    if not stocks:
        return NaturalAlertParseResult(False, error="No stocks in watchlist")

    result = await ai.complete_json(_system_prompt(), _user_prompt(cleaned, stocks))
    if not result.ok:
        return NaturalAlertParseResult(False, error=result.error or "AI parser failed")

    try:
        payload = _parse_json(result.content)
        plan = _plan_from_payload(payload, cleaned, stocks, default_cooldown)
    except ValueError as exc:
        return NaturalAlertParseResult(False, error=str(exc))
    return NaturalAlertParseResult(True, plan=plan)


def _system_prompt() -> str:
    return (
        "You convert a user's natural-language stock alert request into one JSON object. "
        "Use only the supplied watchlist. Do not invent stocks. "
        "Allowed rule_type values: price_above, price_below, pct_change_above, volume_above, keyword. "
        "For pct_change_above, threshold is a percentage number, for example 5 means +5%. "
        "For volume_above, convert Chinese units such as wan/yi or 万/亿 into raw shares. "
        "For keyword alerts, put the news/announcement keyword in keyword and leave threshold null. "
        "Return JSON only with keys: stock_id, stock_symbol, rule_type, threshold, keyword, name."
    )


def _user_prompt(text: str, stocks: list[Stock]) -> str:
    watchlist = [
        {"id": stock.id, "market": stock.market, "symbol": stock.symbol, "name": stock.name}
        for stock in stocks
        if stock.id is not None
    ]
    return json.dumps({"request": text, "watchlist": watchlist}, ensure_ascii=False)


def _parse_json(content: str) -> dict:
    text = (content or "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("AI did not return JSON") from None
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("AI JSON is not an object")
    return parsed


def _plan_from_payload(payload: dict, original_text: str, stocks: list[Stock], default_cooldown: int) -> NaturalAlertPlan:
    stock = _stock_from_payload(payload, stocks)
    if stock is None or stock.id is None:
        raise ValueError("AI did not match a stock in the watchlist")

    rule_type = str(payload.get("rule_type") or "").strip()
    if rule_type not in ALLOWED_RULE_TYPES:
        raise ValueError("AI returned an unsupported rule type")

    threshold = _optional_float(payload.get("threshold"))
    keyword = str(payload.get("keyword") or "").strip()
    if rule_type == "keyword":
        if not keyword:
            raise ValueError("AI did not return a keyword")
        threshold = None
    elif threshold is None:
        raise ValueError("AI did not return a numeric threshold")

    name = str(payload.get("name") or "").strip() or original_text
    return NaturalAlertPlan(
        stock_id=stock.id,
        name=name[:120],
        rule_type=rule_type,
        threshold=threshold,
        keyword=keyword[:255],
        cooldown_minutes=default_cooldown,
    )


def _stock_from_payload(payload: dict, stocks: list[Stock]) -> Stock | None:
    raw_id = payload.get("stock_id")
    if raw_id is not None:
        try:
            stock_id = int(raw_id)
        except (TypeError, ValueError):
            stock_id = None
        if stock_id is not None:
            for stock in stocks:
                if stock.id == stock_id:
                    return stock

    symbol = str(payload.get("stock_symbol") or payload.get("symbol") or "").strip().upper()
    name = str(payload.get("stock_name") or payload.get("name") or "").strip().upper()
    for stock in stocks:
        if symbol and stock.symbol.upper() == symbol:
            return stock
        if name and stock.name and stock.name.upper() == name:
            return stock
    return None


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
