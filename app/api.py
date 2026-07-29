from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request
from pydantic import BaseModel, Field as PydanticField
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.config import mask_secret, settings
from app.database import engine, get_session
from app.models import (
    AlertEvent,
    AlertRule,
    Announcement,
    AuditLog,
    Brief,
    ChatMessage,
    ChatSession,
    FetchJobRun,
    HistoricalPrice,
    InstitutionalFlow,
    MacroEvent,
    MarketIndexAnalysis,
    MarketIndexPoint,
    MarketQuote,
    NewsItem,
    Notification,
    NotificationSubscription,
    OrderBookSnapshot,
    Stock,
    TradingData,
    User,
    UserWatchlist,
    WebLoginChallenge,
    WebSession,
)
from app.services.ai import DeepSeekClient, fallback_chat_title
from app.services.collector import (
    answer_question,
    collect_all_information,
    collect_announcements,
    collect_macro,
    collect_market_details,
    collect_market_indices,
    collect_news,
    collect_quotes,
    finish_job,
    generate_daily_brief,
    generate_market_index_analysis,
    push_pending_alert_events,
    start_job,
)
from app.services.data_sources import MARKET_INDEX_DEFINITIONS, StockIdentityProvider
from app.services.job_lock import acquire_job_lease, release_job_lease
from app.services.notifications import (
    claim_pending_notifications,
    finish_notification,
    record_subscription_result,
    template_id_for,
)
from app.services.settings_service import get_collection_settings, set_setting, validate_collection_cron
from app.services.users import (
    get_or_create_user,
    get_preference,
    has_deepseek_key,
    set_deepseek_key,
    user_runtime_config,
)


router = APIRouter(prefix="/api/v1")
internal_router = APIRouter(prefix="/internal")
stock_identity_provider = StockIdentityProvider(remote_lookup=False)


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


class ProfilePayload(BaseModel):
    display_name: str = PydanticField(default="", max_length=128)


class WatchlistPayload(BaseModel):
    market: str = PydanticField(min_length=1, max_length=16)
    symbol: str = PydanticField(min_length=1, max_length=32)
    name: str = PydanticField(default="", max_length=128)
    tags: str = PydanticField(default="", max_length=255)


class WatchlistPatch(BaseModel):
    active: bool | None = None
    tags: str | None = PydanticField(default=None, max_length=255)


class BriefPayload(BaseModel):
    stock_id: int | None = None
    latest_hours: int | None = PydanticField(default=None, ge=1, le=168)


class ChatPayload(BaseModel):
    question: str = PydanticField(min_length=1, max_length=4000)


class AlertPayload(BaseModel):
    stock_id: int
    name: str = PydanticField(default="", max_length=128)
    rule_type: Literal["price_above", "price_below", "pct_change_above", "volume_above", "keyword", "ai_brief"]
    threshold: float | None = None
    keyword: str = PydanticField(default="", max_length=255)
    push_mode: Literal["cooldown", "once"] = "cooldown"
    cooldown_minutes: int = PydanticField(default=30, ge=1, le=10080)


class AlertPatch(BaseModel):
    enabled: bool


class SubscriptionPayload(BaseModel):
    template_type: Literal["alert", "brief"]
    result: Literal["accept", "reject", "ban"]


class SettingsPayload(BaseModel):
    deepseek_api_key: str | None = PydanticField(default=None, max_length=500)
    clear_deepseek_api_key: bool = False
    deepseek_model: str | None = None
    daily_brief_enabled: bool | None = None
    daily_brief_time: str | None = None
    market_open_briefs_enabled: bool | None = None
    cn_open_brief_time: str | None = None
    us_open_brief_time: str | None = None


class UserApprovalPayload(BaseModel):
    status: Literal["pending", "active", "disabled"]
    role: Literal["user", "admin"] = "user"


class GlobalSettingsPayload(BaseModel):
    collection_enabled: bool
    collect_all_cron: str | None = PydanticField(default=None, max_length=100)


class NotificationResultPayload(BaseModel):
    success: bool
    error: str = PydanticField(default="", max_length=2000)
    transient: bool = False


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    openid = request.headers.get("x-wx-openid", "").strip()
    if not openid:
        raise ApiError(401, "WECHAT_IDENTITY_REQUIRED", "缺少微信用户身份，请通过小程序云托管私链访问")
    appid = request.headers.get("x-wx-appid", "").strip()
    if appid and settings.wechat_app_id and appid != settings.wechat_app_id:
        raise ApiError(403, "WECHAT_APP_MISMATCH", "请求来自未关联的小程序")
    return get_or_create_user(session, openid)


def active_user(user: User = Depends(current_user)) -> User:
    if user.status != "active":
        raise ApiError(403, "USER_NOT_ACTIVE", "账号正在等待管理员审核" if user.status == "pending" else "账号已停用")
    return user


def admin_user(user: User = Depends(active_user)) -> User:
    if user.role != "admin":
        raise ApiError(403, "ADMIN_REQUIRED", "此操作仅限管理员")
    return user


def internal_auth(x_internal_token: str = Header(default="")) -> None:
    if not settings.internal_api_token or x_internal_token != settings.internal_api_token:
        raise ApiError(401, "INTERNAL_AUTH_FAILED", "内部调用认证失败")


@router.get("/session")
def session_status(user: User = Depends(current_user)) -> dict[str, Any]:
    return {"user": _user_payload(user), "environment": settings.cloudbase_env_id}


@router.patch("/session")
def update_profile(
    payload: ProfilePayload,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user.display_name = payload.display_name.strip()
    session.add(user)
    session.commit()
    return {"user": _user_payload(user)}


@router.get("/dashboard")
def dashboard_api(
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    watchlists = _user_watchlists(session, user.id or 0)
    latest_quotes = _latest_quotes_for(session, [item.stock_id for item in watchlists])
    unread = session.exec(
        select(Notification).where(Notification.user_id == user.id, Notification.read_at == None)  # noqa: E711
    ).all()
    latest_brief = session.exec(
        select(Brief).where(Brief.user_id == user.id).order_by(col(Brief.generated_at).desc()).limit(1)
    ).first()
    latest_jobs = []
    if user.role == "admin":
        latest_jobs = session.exec(select(FetchJobRun).order_by(col(FetchJobRun.started_at).desc()).limit(5)).all()
    return {
        "watchlist_count": len(watchlists),
        "unread_notification_count": len(unread),
        "quotes": [_watchlist_payload(session, item, latest_quotes.get(item.stock_id)) for item in watchlists],
        "latest_brief": _dump(latest_brief),
        "jobs": [_dump(item) for item in latest_jobs],
    }


@router.get("/watchlists")
def list_watchlists(
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    items = _user_watchlists(session, user.id or 0)
    latest_quotes = _latest_quotes_for(session, [item.stock_id for item in items])
    return {"items": [_watchlist_payload(session, item, latest_quotes.get(item.stock_id)) for item in items]}


@router.post("/watchlists", status_code=201)
def add_watchlist(
    payload: WatchlistPayload,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    resolved = stock_identity_provider.resolve(payload.market, payload.symbol)
    if resolved is None:
        raise ApiError(422, "INVALID_STOCK_SYMBOL", "股票市场或代码格式不正确")
    stock = session.exec(
        select(Stock).where(Stock.market == resolved.market, Stock.symbol == resolved.symbol)
    ).first()
    if stock is None:
        stock = Stock(
            market=resolved.market,
            symbol=resolved.symbol,
            name=payload.name.strip() or resolved.name,
            active=True,
        )
        session.add(stock)
        try:
            session.commit()
            session.refresh(stock)
        except IntegrityError:
            session.rollback()
            stock = session.exec(
                select(Stock).where(Stock.market == resolved.market, Stock.symbol == resolved.symbol)
            ).first()
            if stock is None:
                raise ApiError(409, "STOCK_CREATE_CONFLICT", "股票主记录创建冲突，请重试")
    else:
        stock.active = True
        if payload.name.strip():
            stock.name = payload.name.strip()
        session.add(stock)
    item = session.exec(
        select(UserWatchlist).where(UserWatchlist.user_id == user.id, UserWatchlist.stock_id == stock.id)
    ).first()
    if item is None:
        item = UserWatchlist(user_id=user.id or 0, stock_id=stock.id or 0, tags=payload.tags.strip())
    else:
        item.active = True
        item.tags = payload.tags.strip()
    session.add(item)
    session.commit()
    session.refresh(item)
    return _watchlist_payload(session, item, None)


@router.patch("/watchlists/{watchlist_id}")
def update_watchlist(
    watchlist_id: int,
    payload: WatchlistPatch,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = _owned(session, UserWatchlist, watchlist_id, user.id or 0)
    if payload.active is not None:
        item.active = payload.active
    if payload.tags is not None:
        item.tags = payload.tags.strip()
    session.add(item)
    session.commit()
    _refresh_stock_activity(session, item.stock_id)
    return _watchlist_payload(session, item, None)


@router.delete("/watchlists/{watchlist_id}")
def delete_watchlist(
    watchlist_id: int,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    item = _owned(session, UserWatchlist, watchlist_id, user.id or 0)
    stock_id = item.stock_id
    session.delete(item)
    session.commit()
    _refresh_stock_activity(session, stock_id)
    return {"deleted": True}


INFO_MODELS = {
    "quotes": (MarketQuote, MarketQuote.observed_at),
    "history": (HistoricalPrice, HistoricalPrice.trade_date),
    "trading": (TradingData, TradingData.observed_at),
    "order_book": (OrderBookSnapshot, OrderBookSnapshot.observed_at),
    "institutional": (InstitutionalFlow, InstitutionalFlow.observed_at),
    "news": (NewsItem, NewsItem.created_at),
    "announcements": (Announcement, Announcement.created_at),
    "macro": (MacroEvent, MacroEvent.created_at),
}


@router.get("/info/{kind}")
def list_info(
    kind: str,
    limit: int = 30,
    cursor: int | None = None,
    stock_id: int | None = None,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    definition = INFO_MODELS.get(kind)
    if definition is None:
        raise ApiError(404, "INFO_KIND_NOT_FOUND", "未知的信息类型")
    model, _ = definition
    stmt = select(model)
    if cursor is not None:
        stmt = stmt.where(model.id < cursor)
    if stock_id is not None and hasattr(model, "stock_id"):
        stmt = stmt.where(model.stock_id == stock_id)
    rows = session.exec(stmt.order_by(col(model.id).desc()).limit(min(max(limit, 1), 100) + 1)).all()
    has_more = len(rows) > min(max(limit, 1), 100)
    rows = rows[: min(max(limit, 1), 100)]
    stocks = {item.id: item for item in session.exec(select(Stock)).all()}
    items = []
    for row in rows:
        item = _dump(row)
        row_stock_id = getattr(row, "stock_id", None)
        if row_stock_id in stocks:
            item["stock"] = _dump(stocks[row_stock_id])
        items.append(item)
    return {"items": items, "next_cursor": rows[-1].id if has_more and rows else None}


RANGE_DAYS = {"1w": 7, "1m": 31, "1y": 366, "10y": 3653}


@router.get("/indices")
def list_indices(
    range: str = "1y",
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if range not in {*RANGE_DAYS, "max"}:
        raise ApiError(422, "INVALID_RANGE", "时间区间必须为 1w、1m、1y、10y 或 max")
    cutoff = datetime.now(timezone.utc) - timedelta(days=RANGE_DAYS[range]) if range != "max" else None
    cards = []
    for definition in MARKET_INDEX_DEFINITIONS:
        stmt = select(MarketIndexPoint).where(MarketIndexPoint.index_code == definition.code)
        if cutoff is not None:
            stmt = stmt.where(MarketIndexPoint.observed_at >= cutoff)
        points = session.exec(stmt.order_by(MarketIndexPoint.observed_at)).all()
        points = _daily_points(points)
        points = _downsample(points, 1200)
        latest = session.exec(
            select(MarketIndexPoint)
            .where(MarketIndexPoint.index_code == definition.code)
            .order_by(col(MarketIndexPoint.observed_at).desc())
            .limit(1)
        ).first()
        cards.append(
            {
                "definition": {
                    "code": definition.code,
                    "name": definition.name,
                    "symbol": definition.symbol,
                    "unit": definition.unit,
                    "description": definition.description,
                    "source": definition.source,
                    "source_url": definition.source_url,
                },
                "latest": _dump(latest),
                "series": [{"date": point.observed_at.date().isoformat(), "value": point.value} for point in points],
            }
        )
    analysis = session.exec(
        select(MarketIndexAnalysis)
        .where(MarketIndexAnalysis.user_id == user.id)
        .order_by(col(MarketIndexAnalysis.generated_at).desc())
        .limit(1)
    ).first()
    return {"range": range, "cards": cards, "analysis": _dump(analysis)}


@router.post("/indices/analyze")
async def analyze_indices(
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_deepseek_key(session, user.id or 0)
    analysis = await generate_market_index_analysis(session, user_id=user.id)
    return _dump(analysis)


@router.get("/briefs")
def list_briefs(
    limit: int = 30,
    cursor: int | None = None,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(Brief).where(Brief.user_id == user.id)
    if cursor is not None:
        stmt = stmt.where(Brief.id < cursor)
    rows = session.exec(stmt.order_by(col(Brief.generated_at).desc()).limit(min(max(limit, 1), 100) + 1)).all()
    page_size = min(max(limit, 1), 100)
    return {
        "items": [_dump(item) for item in rows[:page_size]],
        "next_cursor": rows[page_size - 1].id if len(rows) > page_size else None,
    }


@router.get("/briefs/{brief_id}")
def get_brief(
    brief_id: int,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _dump(_owned(session, Brief, brief_id, user.id or 0))


@router.post("/briefs", status_code=201)
async def create_brief(
    payload: BriefPayload,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_deepseek_key(session, user.id or 0)
    if payload.stock_id is not None:
        _owned_watchlist_by_stock(session, user.id or 0, payload.stock_id)
    item = await generate_daily_brief(
        session,
        stock_id=payload.stock_id,
        latest_hours=payload.latest_hours,
        user_id=user.id,
        push=True,
    )
    return _dump(item)


@router.delete("/briefs/{brief_id}")
def delete_brief(
    brief_id: int,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    item = _owned(session, Brief, brief_id, user.id or 0)
    session.delete(item)
    session.commit()
    return {"deleted": True}


@router.get("/chat/sessions")
def list_chat_sessions(
    limit: int = 30,
    cursor: int | None = None,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    page_size = min(max(limit, 1), 100)
    statement = select(ChatSession).where(ChatSession.user_id == user.id)
    if cursor is not None:
        statement = statement.where(ChatSession.id < cursor)
    rows = session.exec(statement.order_by(col(ChatSession.id).desc()).limit(page_size + 1)).all()
    return {
        "items": [_dump(item) for item in rows[:page_size]],
        "next_cursor": rows[page_size - 1].id if len(rows) > page_size else None,
    }


@router.post("/chat/sessions", status_code=201)
def create_chat_session(
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = ChatSession(user_id=user.id)
    session.add(item)
    session.commit()
    session.refresh(item)
    return _dump(item)


@router.get("/chat/sessions/{chat_session_id}/messages")
def list_chat_messages(
    chat_session_id: int,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _owned(session, ChatSession, chat_session_id, user.id or 0)
    rows = session.exec(
        select(ChatMessage).where(ChatMessage.session_id == chat_session_id).order_by(ChatMessage.created_at)
    ).all()
    return {"items": [_dump(item) for item in rows]}


@router.post("/chat/sessions/{chat_session_id}/messages", status_code=201)
async def send_chat_message(
    chat_session_id: int,
    payload: ChatPayload,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    chat_session = _owned(session, ChatSession, chat_session_id, user.id or 0)
    _require_deepseek_key(session, user.id or 0)
    question = payload.question.strip()
    user_message = ChatMessage(session_id=chat_session_id, role="user", content=question)
    session.add(user_message)
    session.commit()
    answer = await answer_question(session, question, user_id=user.id)
    assistant_message = ChatMessage(session_id=chat_session_id, role="assistant", content=answer)
    session.add(assistant_message)
    if not chat_session.title or chat_session.title == "新的对话":
        result = await DeepSeekClient(user_runtime_config(session, user.id or 0)).summarize_chat_title(question, answer)
        chat_session.title = result.content or fallback_chat_title(question)
        session.add(chat_session)
    session.commit()
    session.refresh(assistant_message)
    return {"message": _dump(assistant_message), "session": _dump(chat_session)}


@router.delete("/chat/sessions/{chat_session_id}")
def delete_chat_session(
    chat_session_id: int,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    item = _owned(session, ChatSession, chat_session_id, user.id or 0)
    messages = session.exec(select(ChatMessage).where(ChatMessage.session_id == chat_session_id)).all()
    for message in messages:
        session.delete(message)
    session.delete(item)
    session.commit()
    return {"deleted": True}


@router.get("/alerts")
def list_alerts(
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    rules = session.exec(
        select(AlertRule).where(AlertRule.user_id == user.id).order_by(col(AlertRule.created_at).desc())
    ).all()
    events = session.exec(
        select(AlertEvent).where(AlertEvent.user_id == user.id).order_by(col(AlertEvent.created_at).desc()).limit(50)
    ).all()
    stocks = {item.id: item for item in session.exec(select(Stock)).all()}
    return {
        "rules": [{**_dump(item), "stock": _dump(stocks.get(item.stock_id))} for item in rules],
        "events": [{**_dump(item), "stock": _dump(stocks.get(item.stock_id))} for item in events],
    }


@router.post("/alerts", status_code=201)
def create_alert(
    payload: AlertPayload,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _owned_watchlist_by_stock(session, user.id or 0, payload.stock_id)
    if payload.rule_type == "keyword" and not payload.keyword.strip():
        raise ApiError(422, "KEYWORD_REQUIRED", "关键词提醒必须填写关键词")
    if payload.rule_type == "ai_brief":
        _require_deepseek_key(session, user.id or 0)
    item = AlertRule(
        user_id=user.id,
        stock_id=payload.stock_id,
        name=payload.name.strip(),
        rule_type=payload.rule_type,
        threshold=payload.threshold,
        keyword=payload.keyword.strip(),
        push_mode=payload.push_mode,
        cooldown_minutes=payload.cooldown_minutes,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _dump(item)


@router.get("/alerts/events/{event_id}")
def get_alert_event(
    event_id: int,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = _owned(session, AlertEvent, event_id, user.id or 0)
    return {**_dump(item), "stock": _dump(session.get(Stock, item.stock_id))}


@router.patch("/alerts/{rule_id}")
def update_alert(
    rule_id: int,
    payload: AlertPatch,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = _owned(session, AlertRule, rule_id, user.id or 0)
    item.enabled = payload.enabled
    session.add(item)
    session.commit()
    return _dump(item)


@router.delete("/alerts/{rule_id}")
def delete_alert_api(
    rule_id: int,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    item = _owned(session, AlertRule, rule_id, user.id or 0)
    events = session.exec(select(AlertEvent).where(AlertEvent.rule_id == rule_id)).all()
    for event in events:
        if session.get_bind().dialect.name == "sqlite":
            session.delete(event)
        else:
            event.rule_id = None
            session.add(event)
    session.delete(item)
    session.commit()
    return {"deleted": True}


@router.get("/notifications")
def list_notifications(
    limit: int = 50,
    cursor: int | None = None,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    page_size = min(max(limit, 1), 100)
    statement = select(Notification).where(Notification.user_id == user.id)
    if cursor is not None:
        statement = statement.where(Notification.id < cursor)
    rows = session.exec(statement.order_by(col(Notification.id).desc()).limit(page_size + 1)).all()
    return {
        "items": [_dump(item) for item in rows[:page_size]],
        "next_cursor": rows[page_size - 1].id if len(rows) > page_size else None,
    }


@router.post("/notifications/{notification_id}/read")
def read_notification(
    notification_id: int,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = _owned(session, Notification, notification_id, user.id or 0)
    item.read_at = datetime.now(timezone.utc)
    session.add(item)
    session.commit()
    return _dump(item)


@router.get("/notifications/templates")
def notification_templates(user: User = Depends(active_user)) -> dict[str, str]:
    return {"alert": template_id_for("alert"), "brief": template_id_for("brief")}


@router.post("/notifications/subscriptions")
def save_subscription(
    payload: SubscriptionPayload,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = record_subscription_result(
        session,
        user_id=user.id or 0,
        template_type=payload.template_type,
        result=payload.result,
    )
    return _dump(item)


@router.get("/settings")
def get_user_settings(
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    preference = get_preference(session, user.id or 0)
    subscriptions = session.exec(
        select(NotificationSubscription).where(NotificationSubscription.user_id == user.id)
    ).all()
    return {
        "preference": _dump(preference),
        "deepseek_key_configured": has_deepseek_key(session, user.id or 0),
        "deepseek_key_masked": "已安全保存" if has_deepseek_key(session, user.id or 0) else "",
        "allowed_models": list(settings.allowed_deepseek_models),
        "subscriptions": [_dump(item) for item in subscriptions],
    }


@router.put("/settings")
def update_user_settings(
    payload: SettingsPayload,
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    preference = get_preference(session, user.id or 0)
    if payload.deepseek_model is not None:
        if payload.deepseek_model not in settings.allowed_deepseek_models:
            raise ApiError(422, "MODEL_NOT_ALLOWED", "所选 DeepSeek 模型不在允许列表中")
        preference.deepseek_model = payload.deepseek_model
    for field_name in ("daily_brief_time", "cn_open_brief_time", "us_open_brief_time"):
        value = getattr(payload, field_name)
        if value is not None:
            _validate_time(value)
            setattr(preference, field_name, value)
    for field_name in ("daily_brief_enabled", "market_open_briefs_enabled"):
        value = getattr(payload, field_name)
        if value is not None:
            setattr(preference, field_name, value)
    preference.updated_at = datetime.now(timezone.utc)
    session.add(preference)
    session.commit()
    if payload.clear_deepseek_api_key:
        set_deepseek_key(session, user.id or 0, "")
    elif payload.deepseek_api_key is not None and payload.deepseek_api_key.strip():
        try:
            set_deepseek_key(session, user.id or 0, payload.deepseek_api_key)
        except RuntimeError as exc:
            raise ApiError(503, "SECRET_STORAGE_NOT_CONFIGURED", str(exc)) from exc
    return get_user_settings(user, session)


@router.post("/settings/test-deepseek")
async def test_user_deepseek(
    user: User = Depends(active_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        config = user_runtime_config(session, user.id or 0)
    except RuntimeError as exc:
        raise ApiError(503, "SECRET_STORAGE_NOT_CONFIGURED", str(exc)) from exc
    result = await DeepSeekClient(config).test_connection()
    if not result.ok:
        raise ApiError(422, "DEEPSEEK_TEST_FAILED", f"DeepSeek 测试失败：{result.error}")
    return {"ok": True, "message": result.content}


@router.post("/admin/web-login/{challenge_id}/confirm")
def confirm_web_login(
    challenge_id: str,
    user: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    challenge = session.get(WebLoginChallenge, challenge_id)
    now = datetime.now(timezone.utc)
    if challenge is None:
        raise ApiError(404, "CHALLENGE_NOT_FOUND", "登录请求不存在")
    if challenge.status != "pending" or _as_utc(challenge.expires_at) <= now:
        raise ApiError(409, "CHALLENGE_EXPIRED", "登录请求已失效")
    challenge.status = "confirmed"
    challenge.confirmed_by_user_id = user.id
    challenge.confirmed_at = now
    session.add(challenge)
    _audit(session, user.id, "web_login_confirm", challenge_id)
    session.commit()
    return {"confirmed": True}


@router.post("/admin/web-login/{challenge_id}/cancel")
def cancel_web_login(
    challenge_id: str,
    user: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    challenge = session.get(WebLoginChallenge, challenge_id)
    now = datetime.now(timezone.utc)
    if challenge is None:
        raise ApiError(404, "CHALLENGE_NOT_FOUND", "登录请求不存在")
    if challenge.status != "pending" or _as_utc(challenge.expires_at) <= now:
        raise ApiError(409, "CHALLENGE_EXPIRED", "登录请求已失效")
    challenge.status = "cancelled"
    challenge.confirmed_by_user_id = user.id
    challenge.confirmed_at = now
    session.add(challenge)
    _audit(session, user.id, "web_login_cancel", challenge_id)
    session.commit()
    return {"cancelled": True}


@router.get("/admin/users")
def list_users(
    limit: int = 50,
    cursor: int | None = None,
    user: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    page_size = min(max(limit, 1), 100)
    statement = select(User)
    if cursor is not None:
        statement = statement.where(User.id < cursor)
    rows = session.exec(statement.order_by(col(User.id).desc()).limit(page_size + 1)).all()
    return {
        "items": [_user_payload(item) for item in rows[:page_size]],
        "next_cursor": rows[page_size - 1].id if len(rows) > page_size else None,
    }


@router.get("/admin/web-sessions")
def list_web_sessions(
    user: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    rows = session.exec(select(WebSession).order_by(col(WebSession.created_at).desc()).limit(100)).all()
    return {
        "items": [
            {
                **_dump(item),
                "token_hash": item.token_hash,
                "token_hash_masked": mask_secret(item.token_hash),
            }
            for item in rows
        ]
    }


@router.post("/admin/web-sessions/{session_hash}/revoke")
def revoke_web_session(
    session_hash: str,
    user: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    item = session.get(WebSession, session_hash)
    if item is None:
        raise ApiError(404, "WEB_SESSION_NOT_FOUND", "Web 会话不存在")
    item.revoked_at = datetime.now(timezone.utc)
    session.add(item)
    _audit(session, user.id, "web_session_revoke", mask_secret(session_hash))
    session.commit()
    return {"revoked": True}


@router.patch("/admin/users/{user_id}")
def approve_user(
    user_id: int,
    payload: UserApprovalPayload,
    admin: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    target = session.get(User, user_id)
    if target is None:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在")
    protected_admin = target.id == admin.id or target.openid in settings.admin_openids
    if protected_admin and (payload.status != "active" or payload.role != "admin"):
        raise ApiError(409, "ADMIN_SELF_PROTECTION", "不能停用或降级当前/引导管理员")
    target.status = payload.status
    target.role = payload.role
    target.approved_at = datetime.now(timezone.utc) if payload.status == "active" else target.approved_at
    session.add(target)
    _audit(session, admin.id, "user_approval", f"user:{target.id}", f"{payload.status}/{payload.role}")
    session.commit()
    return _user_payload(target)


@router.get("/admin/jobs")
def list_jobs_api(
    limit: int = 50,
    cursor: int | None = None,
    user: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    page_size = min(max(limit, 1), 100)
    statement = select(FetchJobRun)
    if cursor is not None:
        statement = statement.where(FetchJobRun.id < cursor)
    rows = session.exec(statement.order_by(col(FetchJobRun.id).desc()).limit(page_size + 1)).all()
    return {
        "items": [_dump(item) for item in rows[:page_size]],
        "next_cursor": rows[page_size - 1].id if len(rows) > page_size else None,
    }


@router.post("/admin/jobs/{job_name}", status_code=202)
def run_job_api(
    job_name: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if job_name not in {"quotes", "details", "news", "announcements", "macro", "indices", "all"}:
        raise ApiError(404, "JOB_NOT_FOUND", "未知的采集任务")
    run = start_job(session, f"manual_{job_name}", user_id=user.id)
    background_tasks.add_task(_execute_job, run.id or 0, job_name)
    _audit(session, user.id, "manual_job", job_name)
    session.commit()
    return {"job_id": run.id, "status": run.status}


@router.get("/admin/settings")
def get_global_settings(
    user: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    enabled, cron = get_collection_settings(session)
    return {"collection_enabled": enabled, "collect_all_cron": cron}


@router.put("/admin/settings")
def update_global_settings(
    payload: GlobalSettingsPayload,
    user: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _, current_cron = get_collection_settings(session)
    try:
        cron = validate_collection_cron(payload.collect_all_cron or current_cron)
    except ValueError as exc:
        raise ApiError(422, "INVALID_CRON", str(exc)) from exc
    set_setting(session, "collection_enabled", "true" if payload.collection_enabled else "false")
    set_setting(session, "collect_all_cron", cron)
    from app.main import scheduler
    from app.scheduler import configure_collection_job

    configure_collection_job(scheduler, payload.collection_enabled, cron)
    _audit(session, user.id, "global_settings", "collection", f"{payload.collection_enabled}/{cron}")
    session.commit()
    return {"collection_enabled": payload.collection_enabled, "collect_all_cron": cron}


@router.delete("/admin/info/{kind}/{item_id}")
def delete_shared_info(
    kind: str,
    item_id: int,
    user: User = Depends(admin_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    definition = INFO_MODELS.get(kind)
    if definition is None:
        raise ApiError(404, "INFO_KIND_NOT_FOUND", "未知的信息类型")
    item = session.get(definition[0], item_id)
    if item is None:
        raise ApiError(404, "ITEM_NOT_FOUND", "记录不存在")
    session.delete(item)
    _audit(session, user.id, "delete_shared_info", f"{kind}:{item_id}")
    session.commit()
    return {"deleted": True}


@internal_router.post("/notifications/claim")
def claim_notifications(
    limit: int = 20,
    _: None = Depends(internal_auth),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return {"items": claim_pending_notifications(session, limit=limit)}


@internal_router.post("/notifications/{notification_id}/result")
def notification_result(
    notification_id: int,
    payload: NotificationResultPayload,
    _: None = Depends(internal_auth),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = finish_notification(
        session,
        notification_id,
        success=payload.success,
        error=payload.error,
        transient=payload.transient,
    )
    if item is None:
        raise ApiError(404, "NOTIFICATION_NOT_FOUND", "通知不存在")
    return _dump(item)


def _execute_job(job_id: int, job_name: str) -> None:
    async def action(session: Session) -> None:
        if job_name == "quotes":
            await collect_quotes(session)
        elif job_name == "details":
            await collect_market_details(session)
        elif job_name == "news":
            await collect_news(session)
        elif job_name == "announcements":
            await collect_announcements(session)
        elif job_name == "macro":
            await collect_macro(session)
        elif job_name == "indices":
            await collect_market_indices(session)
        elif job_name == "all":
            await collect_all_information(session)
        await push_pending_alert_events(session)

    with Session(engine) as session:
        run = session.get(FetchJobRun, job_id)
        if run is None:
            return
        lease_owner = acquire_job_lease(session, "collection:global", ttl_seconds=3600)
        if lease_owner is None:
            finish_job(session, run, "skipped", "另一个云托管实例正在执行采集任务")
            return
        try:
            asyncio.run(action(session))
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))
        finally:
            release_job_lease(session, "collection:global", lease_owner)


def _user_payload(user: User) -> dict[str, Any]:
    return _json_value({
        "id": user.id,
        "display_name": user.display_name,
        "status": user.status,
        "role": user.role,
        "openid_masked": mask_secret(user.openid),
        "created_at": user.created_at,
        "approved_at": user.approved_at,
    })


def _user_watchlists(session: Session, user_id: int) -> list[UserWatchlist]:
    return list(
        session.exec(
            select(UserWatchlist)
            .where(UserWatchlist.user_id == user_id)
            .order_by(col(UserWatchlist.created_at).desc())
        ).all()
    )


def _latest_quotes_for(session: Session, stock_ids: list[int]) -> dict[int, MarketQuote]:
    result: dict[int, MarketQuote] = {}
    for stock_id in stock_ids:
        item = session.exec(
            select(MarketQuote)
            .where(MarketQuote.stock_id == stock_id)
            .order_by(col(MarketQuote.observed_at).desc())
            .limit(1)
        ).first()
        if item is not None:
            result[stock_id] = item
    return result


def _watchlist_payload(session: Session, item: UserWatchlist, quote: MarketQuote | None) -> dict[str, Any]:
    stock = session.get(Stock, item.stock_id)
    return {**_dump(item), "stock": _dump(stock), "quote": _dump(quote)}


def _owned(session: Session, model: Any, item_id: int, user_id: int):
    item = session.get(model, item_id)
    if item is None:
        raise ApiError(404, "ITEM_NOT_FOUND", "记录不存在")
    if getattr(item, "user_id", None) != user_id:
        raise ApiError(404, "ITEM_NOT_FOUND", "记录不存在")
    return item


def _owned_watchlist_by_stock(session: Session, user_id: int, stock_id: int) -> UserWatchlist:
    item = session.exec(
        select(UserWatchlist).where(
            UserWatchlist.user_id == user_id,
            UserWatchlist.stock_id == stock_id,
            UserWatchlist.active == True,  # noqa: E712
        )
    ).first()
    if item is None:
        raise ApiError(404, "WATCHLIST_NOT_FOUND", "该股票不在你的启用自选股中")
    return item


def _refresh_stock_activity(session: Session, stock_id: int) -> None:
    stock = session.get(Stock, stock_id)
    if stock is None:
        return
    active_relation = session.exec(
        select(UserWatchlist.id).where(
            UserWatchlist.stock_id == stock_id,
            UserWatchlist.active == True,  # noqa: E712
        )
    ).first()
    stock.active = active_relation is not None
    session.add(stock)
    session.commit()


def _daily_points(points: list[MarketIndexPoint]) -> list[MarketIndexPoint]:
    by_day: dict[object, MarketIndexPoint] = {}
    for item in points:
        by_day[item.observed_at.date()] = item
    return list(by_day.values())


def _downsample(items: list[Any], maximum: int) -> list[Any]:
    if len(items) <= maximum:
        return items
    step = (len(items) - 1) / (maximum - 1)
    indices = {round(index * step) for index in range(maximum)}
    return [item for index, item in enumerate(items) if index in indices]


def _validate_time(value: str) -> None:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
    except (ValueError, AttributeError) as exc:
        raise ApiError(422, "INVALID_TIME", "时间必须使用 HH:MM 格式") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59) or len(value) != 5:
        raise ApiError(422, "INVALID_TIME", "时间必须使用 HH:MM 格式")


def _require_deepseek_key(session: Session, user_id: int) -> None:
    if not has_deepseek_key(session, user_id):
        raise ApiError(422, "DEEPSEEK_KEY_REQUIRED", "请先在个人设置中保存 DeepSeek API Key")


def _audit(session: Session, user_id: int | None, action: str, target: str = "", detail: str = "") -> None:
    session.add(AuditLog(user_id=user_id, action=action, target=target, detail=detail))


def _dump(item: Any) -> dict[str, Any] | None:
    if item is None:
        return None
    if hasattr(item, "model_dump"):
        return _json_value(item.model_dump())
    return _json_value(dict(item))


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _as_utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
