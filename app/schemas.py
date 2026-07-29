from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class NormalizedQuote:
    symbol: str
    market: str
    price: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    previous_close: float | None = None
    change_percent: float | None = None
    volume: float | None = None
    volume_ratio: float | None = None
    volume_signal: str = ""
    source: str = ""


@dataclass
class NormalizedTradingData:
    symbol: str
    market: str
    price: float | None = None
    change_percent: float | None = None
    volume: float | None = None
    volume_ratio: float | None = None
    volume_signal: str = ""
    turnover: float | None = None
    source: str = ""
    raw_data: str = ""


@dataclass
class NormalizedHistoricalPrice:
    symbol: str
    market: str
    trade_date: datetime
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    source: str = ""


@dataclass
class NormalizedOrderBook:
    symbol: str
    market: str
    source: str
    levels: str


@dataclass
class NormalizedInstitutionalFlow:
    symbol: str
    market: str
    source: str
    vwap_proxy: float | None = None
    cost_low: float | None = None
    cost_high: float | None = None
    dark_pool_volume: float | None = None
    off_exchange_volume: float | None = None
    sample_days: int = 0
    raw_data: str = ""


@dataclass
class NormalizedMarketIndex:
    code: str
    name: str
    value: float
    observed_at: datetime
    unit: str = ""
    status: str = ""
    source: str = ""


@dataclass
class ResolvedStock:
    market: str
    symbol: str
    name: str
    source: str


@dataclass
class NormalizedArticle:
    title: str
    source: str
    url: str = ""
    summary: str = ""
    published_at: datetime | None = None
    stock_symbol: str | None = None
    stock_market: str | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
