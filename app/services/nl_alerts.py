from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import Stock


def _u(*codepoints: int) -> str:
    return "".join(chr(codepoint) for codepoint in codepoints)


UNIT_WAN = _u(0x4E07)
UNIT_YI_SIMPLIFIED = _u(0x4EBF)
UNIT_YI_TRADITIONAL = _u(0x5104)
NUMBER_RE = re.compile(rf"(-?\d+(?:\.\d+)?)\s*([{UNIT_WAN}{UNIT_YI_SIMPLIFIED}{UNIT_YI_TRADITIONAL}kKmMbB%]*)")
QUOTE_RE = re.compile(
    "[" + re.escape("\"'" + _u(0x201C, 0x201D, 0x2018, 0x2019, 0x300C, 0x300D, 0x300E, 0x300F)) + "]"
    + "(.+?)"
    + "[" + re.escape("\"'" + _u(0x201C, 0x201D, 0x2018, 0x2019, 0x300C, 0x300D, 0x300E, 0x300F)) + "]"
)
XIAOMI = _u(0x5C0F, 0x7C73)


@dataclass
class NaturalAlertPlan:
    stock_id: int
    name: str
    rule_type: str
    threshold: float | None = None
    keyword: str = ""
    cooldown_minutes: int = 30


def parse_natural_alert(text: str, stocks: list[Stock], default_cooldown: int = 30) -> NaturalAlertPlan | None:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return None
    stock = _find_stock(cleaned, stocks)
    if stock is None or stock.id is None:
        return None

    rule_type = _rule_type(cleaned)
    if rule_type == "keyword":
        keyword = _keyword(cleaned, stock)
        if not keyword:
            return None
        return NaturalAlertPlan(
            stock_id=stock.id,
            name=cleaned[:120],
            rule_type="keyword",
            keyword=keyword[:255],
            cooldown_minutes=default_cooldown,
        )

    threshold = _threshold(cleaned)
    if rule_type is None or threshold is None:
        return None
    return NaturalAlertPlan(
        stock_id=stock.id,
        name=cleaned[:120],
        rule_type=rule_type,
        threshold=threshold,
        cooldown_minutes=default_cooldown,
    )


def _find_stock(text: str, stocks: list[Stock]) -> Stock | None:
    upper_text = text.upper()
    exact_matches = [
        stock
        for stock in stocks
        if stock.symbol.upper() in upper_text or (stock.name and stock.name.upper() in upper_text) or _matches_alias(text, stock)
    ]
    if exact_matches:
        return sorted(exact_matches, key=lambda item: len(item.symbol), reverse=True)[0]
    return None


def _matches_alias(text: str, stock: Stock) -> bool:
    if XIAOMI in text and (stock.symbol in {"1810", "01810"} or "XIAOMI" in stock.name.upper()):
        return True
    return False


def _rule_type(text: str) -> str | None:
    if _has_any(text, [_u(0x516C, 0x544A), _u(0x65B0, 0x95FB), _u(0x5173, 0x952E, 0x8BCD)]):
        return "keyword"
    if _has_any(text, [_u(0x6210, 0x4EA4, 0x91CF), _u(0x653E, 0x91CF), _u(0x91CF, 0x80FD)]):
        return "volume_above"
    if _has_any(text, [_u(0x6DA8, 0x5E45), _u(0x6DA8, 0x8DCC, 0x5E45), _u(0x4E0A, 0x6DA8)]):
        return "pct_change_above"
    if _has_any(text, [_u(0x4F4E, 0x4E8E), _u(0x8DCC, 0x7834), _u(0x5C0F, 0x4E8E), _u(0x4E0B, 0x7834)]):
        return "price_below"
    if _has_any(text, [_u(0x9AD8, 0x4E8E), _u(0x8D85, 0x8FC7), _u(0x5927, 0x4E8E), _u(0x7A81, 0x7834), _u(0x7AD9, 0x4E0A)]):
        return "price_above"
    return None


def _threshold(text: str) -> float | None:
    matches = list(NUMBER_RE.finditer(text))
    if not matches:
        return None
    value, unit = matches[-1].groups()
    number = float(value)
    unit = unit.lower().replace(UNIT_YI_TRADITIONAL, UNIT_YI_SIMPLIFIED)
    if UNIT_YI_SIMPLIFIED in unit or "b" in unit:
        return number * 100_000_000
    if UNIT_WAN in unit:
        return number * 10_000
    if "m" in unit:
        return number * 1_000_000
    if "k" in unit:
        return number * 1_000
    return number


def _keyword(text: str, stock: Stock) -> str:
    quoted = QUOTE_RE.search(text)
    if quoted:
        return quoted.group(1).strip()

    markers = [
        _u(0x51FA, 0x73B0),
        _u(0x5305, 0x542B),
        _u(0x63D0, 0x5230),
        _u(0x5173, 0x952E, 0x8BCD),
        _u(0x5339, 0x914D),
    ]
    for marker in markers:
        if marker in text:
            candidate = text.split(marker, 1)[1]
            return _clean_keyword(candidate)

    candidate = text
    for token in [stock.symbol, stock.name, _u(0x516C, 0x544A), _u(0x65B0, 0x95FB), _u(0x63D0, 0x9192), _u(0x76D1, 0x63A7)]:
        if token:
            candidate = candidate.replace(token, " ")
    return _clean_keyword(candidate)


def _clean_keyword(text: str) -> str:
    stop_words = [
        _u(0x5C31),
        _u(0x65F6),
        _u(0x7ED9, 0x6211),
        _u(0x63A8, 0x9001),
        _u(0x63D0, 0x9192),
        _u(0x901A, 0x77E5),
    ]
    cleaned = text
    for word in stop_words:
        cleaned = cleaned.replace(word, " ")
    return " ".join(cleaned.strip(" ;,.").strip(_u(0xFF0C, 0x3002, 0xFF1B)).split())


def _has_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)
