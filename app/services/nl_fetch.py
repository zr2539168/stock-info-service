from __future__ import annotations

import re
from dataclasses import dataclass

from sqlmodel import Session, select

from app.models import HistoricalPrice, Stock
from app.services.content import content_hash
from app.services.data_sources import MarketDataProvider, StockIdentityProvider
from app.services.stock_parser import normalize_market, normalize_symbol


SYMBOL_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{1,6}(?![A-Z0-9])|(?<!\d)\d{4,6}(?!\d)")


def _u(*codepoints: int) -> str:
    return "".join(chr(codepoint) for codepoint in codepoints)


FETCH_WORDS = [
    _u(0x6293),
    _u(0x83B7, 0x53D6),
    _u(0x62C9, 0x53D6),
    _u(0x66F4, 0x65B0),
    _u(0x4E0B, 0x8F7D),
    _u(0x91C7, 0x96C6),
]
MARKET_DATA_WORDS = [
    _u(0x884C, 0x60C5),
    _u(0x5386, 0x53F2),
    "K" + _u(0x7EBF),
    "k" + _u(0x7EBF),
    _u(0x4EA4, 0x6613, 0x6570, 0x636E),
    _u(0x4EF7, 0x683C),
    _u(0x8D70, 0x52BF),
]


@dataclass
class FetchPlan:
    symbol: str
    market: str
    period: str
    data_kind: str


@dataclass
class FetchExecution:
    executed: bool
    message: str = ""
    rows_saved: int = 0
    stock: Stock | None = None


def plan_fetch_from_text(text: str, stocks: list[Stock]) -> FetchPlan | None:
    if not _looks_like_fetch_request(text):
        return None
    if not _looks_like_market_data_request(text):
        return None
    stock = _find_stock_in_text(text, stocks)
    if stock is not None:
        return FetchPlan(symbol=stock.symbol, market=stock.market, period=_period_from_text(text), data_kind="history")

    symbol = _first_symbol(text)
    if not symbol:
        return None
    return FetchPlan(symbol=symbol, market=_infer_market(symbol), period=_period_from_text(text), data_kind="history")


def execute_fetch_plan(
    session: Session,
    plan: FetchPlan,
    provider: MarketDataProvider | None = None,
    identity_provider: StockIdentityProvider | None = None,
) -> FetchExecution:
    if plan.data_kind != "history":
        return FetchExecution(False, _u(0x6682, 0x4E0D, 0x652F, 0x6301, 0x8BE5, 0x6570, 0x636E, 0x7C7B, 0x578B, 0x3002))

    stock = _get_or_create_stock(session, plan, identity_provider or StockIdentityProvider())
    if stock is None or stock.id is None:
        return FetchExecution(False, f"{_u(0x672A, 0x80FD, 0x8BC6, 0x522B)} {plan.market} {plan.symbol}{_u(0x3002)}")

    prices = (provider or MarketDataProvider()).fetch_historical_prices(stock.market, stock.symbol, plan.period)
    rows_saved = 0
    for price in prices:
        digest = content_hash(str(stock.id), price.trade_date.isoformat(), price.source)
        exists = session.exec(select(HistoricalPrice).where(HistoricalPrice.content_hash == digest)).first()
        if exists:
            continue
        session.add(
            HistoricalPrice(
                stock_id=stock.id,
                trade_date=price.trade_date,
                open=price.open,
                high=price.high,
                low=price.low,
                close=price.close,
                volume=price.volume,
                source=price.source,
                content_hash=digest,
            )
        )
        rows_saved += 1
    session.commit()
    return FetchExecution(
        bool(prices),
        f"{_u(0x5DF2, 0x6293, 0x53D6)} {stock.market} {stock.symbol} {stock.name} "
        f"{_u(0x7684, 0x5386, 0x53F2, 0x884C, 0x60C5, 0xFF0C, 0x65B0, 0x589E)} {rows_saved} "
        f"{_u(0x6761, 0x3002)}",
        rows_saved,
        stock,
    )


def _looks_like_fetch_request(text: str) -> bool:
    return any(word in text for word in FETCH_WORDS)


def _looks_like_market_data_request(text: str) -> bool:
    return any(word in text for word in MARKET_DATA_WORDS)


def _period_from_text(text: str) -> str:
    year = _u(0x4E00, 0x5E74)
    half_year = _u(0x534A, 0x5E74)
    month = _u(0x4E2A, 0x6708)
    three_months = _u(0x4E09, 0x4E2A, 0x6708)
    quarter = _u(0x4E00, 0x5B63, 0x5EA6)
    week = _u(0x4E00, 0x5468)
    day = _u(0x5929)
    if year in text or f"1{_u(0x5E74)}" in text:
        return "1y"
    if half_year in text or f"6{month}" in text:
        return "6mo"
    if three_months in text or f"3{month}" in text or quarter in text:
        return "3mo"
    if week in text or f"7{day}" in text:
        return "5d"
    return "1mo"


def _find_stock_in_text(text: str, stocks: list[Stock]) -> Stock | None:
    upper_text = text.upper()
    for stock in stocks:
        if stock.symbol.upper() in upper_text or (stock.name and stock.name.upper() in upper_text):
            return stock
    return None


def _first_symbol(text: str) -> str | None:
    upper_text = text.upper()
    for match in SYMBOL_RE.finditer(upper_text):
        symbol = match.group(0)
        if symbol not in {"AI", "K"}:
            return symbol
    return None


def _infer_market(symbol: str) -> str:
    if symbol.isdigit():
        return "HK" if len(symbol) in {4, 5} and len(symbol) != 6 else "CN"
    return "US"


def _get_or_create_stock(session: Session, plan: FetchPlan, identity_provider: StockIdentityProvider) -> Stock | None:
    market = normalize_market(plan.market)
    symbol = normalize_symbol(plan.symbol, market)
    stock = session.exec(select(Stock).where(Stock.market == market, Stock.symbol == symbol)).first()
    if stock is not None:
        return stock

    resolved = identity_provider.resolve(market, symbol)
    if resolved is None:
        return None
    stock = Stock(market=resolved.market, symbol=resolved.symbol, name=resolved.name, active=True)
    session.add(stock)
    session.commit()
    session.refresh(stock)
    return stock
