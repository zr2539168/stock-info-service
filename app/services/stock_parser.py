from __future__ import annotations


def normalize_market(market: str) -> str:
    value = (market or "").strip().upper()
    aliases = {
        "A": "CN",
        "ASHARE": "CN",
        "A股": "CN",
        "CN": "CN",
        "US": "US",
        "美股": "US",
        "HK": "HK",
        "港股": "HK",
    }
    return aliases.get(value, value or "CN")


def normalize_symbol(symbol: str, market: str) -> str:
    raw = (symbol or "").strip().upper()
    normalized_market = normalize_market(market)
    if normalized_market == "HK":
        return raw.zfill(4) if raw.isdigit() and len(raw) < 4 else raw
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

