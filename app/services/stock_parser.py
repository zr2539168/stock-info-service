from __future__ import annotations


def normalize_market(market: str) -> str:
    value = (market or "").strip().upper()
    aliases = {
        "A": "CN",
        "ASHARE": "CN",
        "CN": "CN",
        "US": "US",
        "HK": "HK",
    }
    if market == "A股":
        return "CN"
    if market == "美股":
        return "US"
    if market == "港股":
        return "HK"
    return aliases.get(value, value or "CN")


def normalize_symbol(symbol: str, market: str) -> str:
    raw = (symbol or "").strip().upper()
    normalized_market = normalize_market(market)
    if normalized_market == "HK":
        if raw.isdigit():
            stripped = raw.lstrip("0") or "0"
            return stripped.zfill(4) if len(stripped) < 4 else stripped
        return raw
    return raw


def to_yfinance_symbol(symbol: str, market: str) -> str:
    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    if market == "HK" and symbol.isdigit():
        return f"{symbol.zfill(4)}.HK"
    if market == "CN" and symbol.isdigit():
        suffix = ".SS" if symbol.startswith(("6", "9")) else ".SZ"
        return f"{symbol}{suffix}"
    return symbol
