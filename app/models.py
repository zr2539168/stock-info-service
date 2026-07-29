from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "app_user"

    id: Optional[int] = Field(default=None, primary_key=True)
    openid: str = Field(index=True, unique=True, max_length=128)
    display_name: str = Field(default="", max_length=128)
    status: str = Field(default="pending", index=True, max_length=20)
    role: str = Field(default="user", index=True, max_length=20)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    approved_at: Optional[datetime] = None
    last_seen_at: datetime = Field(default_factory=utc_now, index=True)


class Stock(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("market", "symbol", name="uq_stock_market_symbol"),)

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
    raw_data: str = Field(default="", sa_column=Column(Text, nullable=False))
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
    content_hash: str = Field(index=True, unique=True, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)


class OrderBookSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: int = Field(index=True, foreign_key="stock.id")
    source: str = Field(default="", max_length=64)
    levels: str = Field(default="", sa_column=Column(Text, nullable=False))
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
    raw_data: str = Field(default="", sa_column=Column(Text, nullable=False))
    observed_at: datetime = Field(default_factory=utc_now, index=True)


class NewsItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: Optional[int] = Field(default=None, index=True, foreign_key="stock.id")
    source: str = Field(default="", max_length=128)
    title: str = Field(max_length=500)
    url: str = Field(default="", max_length=1000)
    summary: str = Field(default="", sa_column=Column(Text, nullable=False))
    published_at: Optional[datetime] = Field(default=None, index=True)
    content_hash: str = Field(index=True, unique=True, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)


class Announcement(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    stock_id: Optional[int] = Field(default=None, index=True, foreign_key="stock.id")
    source: str = Field(default="", max_length=128)
    title: str = Field(max_length=500)
    url: str = Field(default="", max_length=1000)
    summary: str = Field(default="", sa_column=Column(Text, nullable=False))
    published_at: Optional[datetime] = Field(default=None, index=True)
    content_hash: str = Field(index=True, unique=True, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)


class MacroEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(default="", max_length=128)
    title: str = Field(max_length=500)
    url: str = Field(default="", max_length=1000)
    summary: str = Field(default="", sa_column=Column(Text, nullable=False))
    published_at: Optional[datetime] = Field(default=None, index=True)
    content_hash: str = Field(index=True, unique=True, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)


class UserWatchlist(SQLModel, table=True):
    __tablename__ = "user_watchlist"
    __table_args__ = (UniqueConstraint("user_id", "stock_id", name="uq_user_watchlist_user_stock"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="app_user.id")
    stock_id: int = Field(index=True, foreign_key="stock.id")
    tags: str = Field(default="", max_length=255)
    active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


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
    content_hash: str = Field(index=True, unique=True, max_length=64)


class MarketIndexAnalysis(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True, foreign_key="app_user.id")
    content: str = Field(default="", sa_column=Column(Text, nullable=False))
    context: str = Field(default="", sa_column=Column(Text, nullable=False))
    generated_at: datetime = Field(default_factory=utc_now, index=True)


class Brief(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True, foreign_key="app_user.id")
    stock_id: Optional[int] = Field(default=None, index=True, foreign_key="stock.id")
    scope_key: str = Field(default="", max_length=128, index=True)
    title: str = Field(max_length=255)
    content: str = Field(default="", sa_column=Column(Text, nullable=False))
    sources: str = Field(default="", sa_column=Column(Text, nullable=False))
    generated_at: datetime = Field(default_factory=utc_now, index=True)


class ChatSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True, foreign_key="app_user.id")
    title: str = Field(default="新的对话", max_length=255)
    created_at: datetime = Field(default_factory=utc_now)


class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(index=True, foreign_key="chatsession.id")
    role: str = Field(max_length=20)
    content: str = Field(default="", sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)


class AlertRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True, foreign_key="app_user.id")
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
    user_id: Optional[int] = Field(default=None, index=True, foreign_key="app_user.id")
    rule_id: Optional[int] = Field(default=None, index=True, foreign_key="alertrule.id")
    stock_id: int = Field(index=True, foreign_key="stock.id")
    message: str = Field(default="", sa_column=Column(Text, nullable=False))
    pushed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class FetchJobRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True, foreign_key="app_user.id")
    idempotency_key: str = Field(default="", index=True, max_length=255)
    job_name: str = Field(index=True, max_length=128)
    status: str = Field(max_length=32)
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: Optional[datetime] = None
    error: str = Field(default="", sa_column=Column(Text, nullable=False))


class AiUsageLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True, foreign_key="app_user.id")
    feature: str = Field(index=True, max_length=64)
    model: str = Field(default="", max_length=128)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    ok: bool = Field(default=True)
    error: str = Field(default="", sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class AppSetting(SQLModel, table=True):
    key: str = Field(primary_key=True, max_length=128)
    value: str = Field(default="", sa_column=Column(Text, nullable=False))
    secret: bool = Field(default=False)
    updated_at: datetime = Field(default_factory=utc_now)


class UserPreference(SQLModel, table=True):
    __tablename__ = "user_preference"

    user_id: int = Field(primary_key=True, foreign_key="app_user.id")
    deepseek_model: str = Field(default="deepseek-v4-flash", max_length=128)
    daily_brief_enabled: bool = Field(default=False)
    daily_brief_time: str = Field(default="12:00", max_length=5)
    market_open_briefs_enabled: bool = Field(default=False)
    cn_open_brief_time: str = Field(default="10:00", max_length=5)
    us_open_brief_time: str = Field(default="10:00", max_length=5)
    updated_at: datetime = Field(default_factory=utc_now)


class UserSecret(SQLModel, table=True):
    __tablename__ = "user_secret"
    __table_args__ = (UniqueConstraint("user_id", "kind", name="uq_user_secret_user_kind"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="app_user.id")
    kind: str = Field(index=True, max_length=64)
    ciphertext: str = Field(sa_column=Column(Text, nullable=False))
    nonce: str = Field(max_length=128)
    key_version: int = Field(default=1)
    updated_at: datetime = Field(default_factory=utc_now)


class Notification(SQLModel, table=True):
    __tablename__ = "notification"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="app_user.id")
    notification_type: str = Field(index=True, max_length=32)
    title: str = Field(max_length=255)
    content: str = Field(default="", sa_column=Column(Text, nullable=False))
    page_path: str = Field(default="", max_length=500)
    idempotency_key: str = Field(unique=True, max_length=255)
    status: str = Field(default="pending", index=True, max_length=32)
    attempts: int = Field(default=0)
    last_error: str = Field(default="", sa_column=Column(Text, nullable=False))
    claim_until: Optional[datetime] = Field(default=None, index=True)
    sent_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now, index=True)


class NotificationSubscription(SQLModel, table=True):
    __tablename__ = "notification_subscription"
    __table_args__ = (UniqueConstraint("user_id", "template_type", name="uq_subscription_user_type"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="app_user.id")
    template_type: str = Field(index=True, max_length=32)
    template_id: str = Field(default="", max_length=128)
    grant_count: int = Field(default=0)
    last_result: str = Field(default="", max_length=32)
    updated_at: datetime = Field(default_factory=utc_now)


class WebLoginChallenge(SQLModel, table=True):
    __tablename__ = "web_login_challenge"

    id: str = Field(primary_key=True, max_length=32)
    browser_secret_hash: str = Field(max_length=64)
    status: str = Field(default="pending", index=True, max_length=20)
    confirmed_by_user_id: Optional[int] = Field(default=None, index=True, foreign_key="app_user.id")
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(index=True)
    confirmed_at: Optional[datetime] = None
    consumed_at: Optional[datetime] = None


class WebSession(SQLModel, table=True):
    __tablename__ = "web_session"

    token_hash: str = Field(primary_key=True, max_length=64)
    user_id: int = Field(index=True, foreign_key="app_user.id")
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(index=True)
    revoked_at: Optional[datetime] = None


class DistributedJobLock(SQLModel, table=True):
    __tablename__ = "distributed_job_lock"

    lock_key: str = Field(primary_key=True, max_length=128)
    owner: str = Field(max_length=128)
    expires_at: datetime = Field(index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True, foreign_key="app_user.id")
    action: str = Field(index=True, max_length=128)
    target: str = Field(default="", max_length=255)
    detail: str = Field(default="", sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, index=True)
