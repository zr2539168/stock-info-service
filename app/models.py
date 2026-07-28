from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Stock(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    market: str = Field(index=True, max_length=16)
    symbol: str = Field(index=True, max_length=32)
    name: str = Field(default="", max_length=128)
    tags: str = Field(default="", max_length=255)
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)


class MarketQuote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: int = Field(index=True, foreign_key="stock.id")
    price: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    previous_close: Optional[float] = None
    change_percent: Optional[float] = None
    volume: Optional[float] = None
    volume_ratio: Optional[float] = None
    volume_signal: str = Field(default="", max_length=32)
    source: str = Field(default="", max_length=64)
    observed_at: datetime = Field(default_factory=utc_now, index=True)


class TradingData(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: int = Field(index=True, foreign_key="stock.id")
    price: Optional[float] = None
    change_percent: Optional[float] = None
    volume: Optional[float] = None
    volume_ratio: Optional[float] = None
    volume_signal: str = Field(default="", max_length=32)
    turnover: Optional[float] = None
    source: str = Field(default="", max_length=64)
    raw_data: str = Field(default="")
    observed_at: datetime = Field(default_factory=utc_now, index=True)


class HistoricalPrice(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: int = Field(index=True, foreign_key="stock.id")
    trade_date: datetime = Field(index=True)
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    source: str = Field(default="", max_length=64)
    content_hash: str = Field(index=True, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)


class OrderBookSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: int = Field(index=True, foreign_key="stock.id")
    source: str = Field(default="", max_length=64)
    levels: str = Field(default="")
    observed_at: datetime = Field(default_factory=utc_now, index=True)


class InstitutionalFlow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: int = Field(index=True, foreign_key="stock.id")
    source: str = Field(default="", max_length=128)
    vwap_proxy: Optional[float] = None
    cost_low: Optional[float] = None
    cost_high: Optional[float] = None
    dark_pool_volume: Optional[float] = None
    off_exchange_volume: Optional[float] = None
    sample_days: int = Field(default=0)
    raw_data: str = Field(default="")
    observed_at: datetime = Field(default_factory=utc_now, index=True)


class NewsItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: Optional[int] = Field(default=None, index=True, foreign_key="stock.id")
    source: str = Field(default="", max_length=128)
    title: str = Field(max_length=500)
    url: str = Field(default="", max_length=1000)
    summary: str = Field(default="")
    published_at: Optional[datetime] = Field(default=None, index=True)
    content_hash: str = Field(index=True, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)


class Announcement(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: Optional[int] = Field(default=None, index=True, foreign_key="stock.id")
    source: str = Field(default="", max_length=128)
    title: str = Field(max_length=500)
    url: str = Field(default="", max_length=1000)
    summary: str = Field(default="")
    published_at: Optional[datetime] = Field(default=None, index=True)
    content_hash: str = Field(index=True, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)


class MacroEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(default="", max_length=128)
    title: str = Field(max_length=500)
    url: str = Field(default="", max_length=1000)
    summary: str = Field(default="")
    published_at: Optional[datetime] = Field(default=None, index=True)
    content_hash: str = Field(index=True, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)


class MarketIndexPoint(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    index_code: str = Field(index=True, max_length=32)
    name: str = Field(max_length=128)
    value: float
    unit: str = Field(default="", max_length=16)
    status: str = Field(default="", max_length=64)
    source: str = Field(default="", max_length=128)
    observed_at: datetime = Field(index=True)
    collected_at: datetime = Field(default_factory=utc_now, index=True)
    content_hash: str = Field(index=True, max_length=64)


class MarketIndexAnalysis(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    content: str = Field(default="")
    context: str = Field(default="")
    generated_at: datetime = Field(default_factory=utc_now, index=True)


class Brief(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: Optional[int] = Field(default=None, index=True, foreign_key="stock.id")
    scope_key: str = Field(default="", max_length=128, index=True)
    title: str = Field(max_length=255)
    content: str = Field(default="")
    sources: str = Field(default="")
    generated_at: datetime = Field(default_factory=utc_now, index=True)


class ChatSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(default="新的对话", max_length=255)
    created_at: datetime = Field(default_factory=utc_now)


class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(index=True, foreign_key="chatsession.id")
    role: str = Field(max_length=20)
    content: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now)


class AlertRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: int = Field(index=True, foreign_key="stock.id")
    name: str = Field(default="", max_length=128)
    rule_type: str = Field(max_length=32)
    threshold: Optional[float] = None
    keyword: str = Field(default="", max_length=255)
    push_mode: str = Field(default="cooldown", max_length=32)
    enabled: bool = Field(default=True)
    cooldown_minutes: int = Field(default=30)
    last_triggered_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class AlertEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    rule_id: int = Field(index=True, foreign_key="alertrule.id")
    stock_id: int = Field(index=True, foreign_key="stock.id")
    message: str = Field(default="")
    pushed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class FetchJobRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_name: str = Field(index=True, max_length=128)
    status: str = Field(max_length=32)
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: Optional[datetime] = None
    error: str = Field(default="")


class AiUsageLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    feature: str = Field(index=True, max_length=64)
    model: str = Field(default="", max_length=128)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    ok: bool = Field(default=True)
    error: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now, index=True)


class AppSetting(SQLModel, table=True):
    key: str = Field(primary_key=True, max_length=128)
    value: str = Field(default="")
    secret: bool = Field(default=False)
    updated_at: datetime = Field(default_factory=utc_now)
