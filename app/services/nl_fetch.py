from __future__ import annotations

import re
from dataclasses import dataclass

from sqlmodel import Session, select

from app.models import HistoricalPrice, Stock
from app.services.content import content_hash
from app.services.data_sources import MarketDataProvider, StockIdentityProvider
from app.services.stock_parser import normalize_market, normalize_symbol


SYMBOL_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{1,6}(?![A-Z0-9])|(?<!\d)\d{4,6}(?!\d)")


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
        return FetchExecution(False, "暂不支持该数据类型。")

    stock = _get_or_create_stock(session, plan, identity_provider or StockIdentityProvider())
    if stock is None or stock.id is None:
        return FetchExecution(False, f"未能识别 {plan.market} {plan.symbol}。")

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
        f"已抓取 {stock.market} {stock.symbol} {stock.name} 的历史行情，新增 {rows_saved} 条。",
        rows_saved,
        stock,
    )


def _looks_like_fetch_request(text: str) -> bool:
    return any(word in text for word in ["抓", "获取", "拉取", "更新", "下载", "采集"])


def _looks_like_market_data_request(text: str) -> bool:
    return any(word in text for word in ["行情", "历史", "K线", "k线", "交易数据", "价格", "走势"])


def _period_from_text(text: str) -> str:
    if "一年" in text or "1年" in text:
        return "1y"
    if "半年" in text or "6个月" in text:
        return "6mo"
    if "三个月" in text or "3个月" in text or "一季度" in text:
        return "3mo"
    if "一周" in text or "7天" in text:
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
        return "HK" if len(symbol) in {4, 5} and not len(symbol) == 6 else "CN"
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
