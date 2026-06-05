from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from threading import Thread
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, col, select

from app.config import mask_secret, settings
from app.database import engine, get_session, init_db
from app.markdown import render_markdown
from app.presentation import clean_text, format_beijing_time, replace_stock_refs
from app.models import (
    AlertEvent,
    AlertRule,
    Announcement,
    Brief,
    ChatMessage,
    ChatSession,
    FetchJobRun,
    HistoricalPrice,
    InstitutionalFlow,
    MacroEvent,
    MarketQuote,
    NewsItem,
    OrderBookSnapshot,
    Stock,
    TradingData,
)
from app.scheduler import (
    apply_collection_settings,
    apply_daily_noon_brief_settings,
    apply_market_open_brief_settings,
    build_scheduler,
    configure_collection_job,
    configure_daily_noon_brief_job,
    configure_market_open_brief_jobs,
)
from app.services.ai import DeepSeekClient, fallback_chat_title
from app.services.collector import (
    answer_question,
    collect_all_information,
    collect_announcements,
    collect_macro,
    collect_market_details,
    collect_news,
    collect_quotes,
    finish_job,
    generate_daily_brief,
    push_pending_alert_events,
    start_job,
)
from app.services.data_sources import StockIdentityProvider
from app.services.pushdeer import PushDeerClient
from app.services.job_lock import acquire_collection_job_lock, release_collection_job_lock
from app.services.settings_service import all_settings, daily_time_to_cron, get_runtime_config, set_setting, workday_time_to_cron


templates = Jinja2Templates(directory="app/templates")
templates.env.filters["markdown"] = render_markdown
templates.env.filters["beijing_time"] = format_beijing_time
templates.env.filters["clean_text"] = clean_text
templates.env.filters["stock_refs"] = replace_stock_refs
scheduler = build_scheduler()
stock_identity_provider = StockIdentityProvider()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    apply_collection_settings(scheduler)
    apply_market_open_brief_settings(scheduler)
    apply_daily_noon_brief_settings(scheduler)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def watchlist_redirect(message: str, level: str = "info") -> RedirectResponse:
    return redirect(f"/watchlist?{urlencode({'level': level, 'message': message})}")


INFO_MODELS = {
    "quotes": MarketQuote,
    "history": HistoricalPrice,
    "trading": TradingData,
    "order_book": OrderBookSnapshot,
    "institutional": InstitutionalFlow,
    "news": NewsItem,
    "announcements": Announcement,
    "macro": MacroEvent,
}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    stocks = session.exec(select(Stock).order_by(Stock.market, Stock.symbol)).all()
    latest_quotes = {
        stock.id: session.exec(
            select(MarketQuote)
            .where(MarketQuote.stock_id == stock.id)
            .order_by(col(MarketQuote.observed_at).desc())
            .limit(1)
        ).first()
        for stock in stocks
    }
    briefs = session.exec(select(Brief).order_by(col(Brief.generated_at).desc()).limit(5)).all()
    events = session.exec(select(AlertEvent).order_by(col(AlertEvent.created_at).desc()).limit(8)).all()
    jobs = session.exec(select(FetchJobRun).order_by(col(FetchJobRun.started_at).desc()).limit(8)).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "stocks": stocks,
            "latest_quotes": latest_quotes,
            "briefs": briefs,
            "events": events,
            "jobs": jobs,
        },
    )


@app.get("/watchlist", response_class=HTMLResponse)
def watchlist(request: Request, session: Session = Depends(get_session)):
    stocks = session.exec(select(Stock).order_by(Stock.market, Stock.symbol)).all()
    return templates.TemplateResponse(
        request,
        "watchlist.html",
        {
            "stocks": stocks,
            "message": request.query_params.get("message", ""),
            "message_level": request.query_params.get("level", "info"),
        },
    )


@app.post("/watchlist")
def add_stock(
    market: str = Form(...),
    symbol: str = Form(...),
    name: str = Form(""),
    tags: str = Form(""),
    session: Session = Depends(get_session),
):
    resolved = stock_identity_provider.resolve(market, symbol)
    if resolved is None:
        return watchlist_redirect("未能识别该股票代码，请检查市场和代码是否正确，或稍后再试", "error")
    normalized_market = resolved.market
    normalized_symbol = resolved.symbol
    resolved_name = name.strip() or resolved.name
    existing = session.exec(
        select(Stock).where(Stock.market == normalized_market, Stock.symbol == normalized_symbol)
    ).first()
    if existing:
        existing.name = resolved_name
        existing.tags = tags
        existing.active = True
        session.add(existing)
        message = f"已更新 {normalized_market} {normalized_symbol} {resolved_name}"
    else:
        session.add(Stock(market=normalized_market, symbol=normalized_symbol, name=resolved_name, tags=tags))
        message = f"已添加 {normalized_market} {normalized_symbol} {resolved_name}"
    session.commit()
    return watchlist_redirect(message, "success")


@app.post("/watchlist/{stock_id}/toggle")
def toggle_stock(stock_id: int, session: Session = Depends(get_session)):
    stock = session.get(Stock, stock_id)
    if stock:
        stock.active = not stock.active
        session.add(stock)
        session.commit()
    return redirect("/watchlist")


@app.post("/watchlist/{stock_id}/delete")
def delete_stock(stock_id: int, session: Session = Depends(get_session)):
    stock = session.get(Stock, stock_id)
    if stock:
        session.delete(stock)
        session.commit()
    return redirect("/watchlist")


@app.get("/briefs", response_class=HTMLResponse)
def briefs(request: Request, session: Session = Depends(get_session)):
    items = session.exec(select(Brief).order_by(col(Brief.generated_at).desc()).limit(30)).all()
    stocks = {stock.id: stock for stock in session.exec(select(Stock)).all()}
    return templates.TemplateResponse(request, "briefs.html", {"briefs": items, "stocks": stocks})


@app.post("/briefs/generate")
async def generate_brief(request: Request, session: Session = Depends(get_session)):
    async def action(job_session: Session) -> None:
        await generate_daily_brief(job_session, push=True)

    if is_progress_request(request):
        run = start_background_job("manual_brief", action)
        return {"job_id": run.id, "redirect_url": "/briefs"}

    async def inline_action() -> None:
        await generate_daily_brief(session, push=True)

    await run_tracked_job(session, "manual_brief", inline_action, use_collection_lock=False)
    return redirect("/briefs")


@app.post("/briefs/delete")
def delete_briefs(item_ids: list[int] = Form(default=[]), session: Session = Depends(get_session)):
    for item_id in item_ids:
        item = session.get(Brief, item_id)
        if item is not None:
            session.delete(item)
    session.commit()
    return redirect("/briefs")


@app.get("/info", response_class=HTMLResponse)
def info_library(request: Request, session: Session = Depends(get_session)):
    stocks = {stock.id: stock for stock in session.exec(select(Stock)).all()}
    collection_running = is_collection_running(session)
    data = {
        "quotes": session.exec(select(MarketQuote).order_by(col(MarketQuote.observed_at).desc()).limit(100)).all(),
        "history": session.exec(select(HistoricalPrice).order_by(col(HistoricalPrice.trade_date).desc()).limit(200)).all(),
        "trading": session.exec(select(TradingData).order_by(col(TradingData.observed_at).desc()).limit(100)).all(),
        "order_book": session.exec(
            select(OrderBookSnapshot).order_by(col(OrderBookSnapshot.observed_at).desc()).limit(100)
        ).all(),
        "institutional": session.exec(
            select(InstitutionalFlow).order_by(col(InstitutionalFlow.observed_at).desc()).limit(100)
        ).all(),
        "news": session.exec(select(NewsItem).order_by(col(NewsItem.created_at).desc()).limit(100)).all(),
        "announcements": session.exec(select(Announcement).order_by(col(Announcement.created_at).desc()).limit(100)).all(),
        "macro": session.exec(select(MacroEvent).order_by(col(MacroEvent.created_at).desc()).limit(100)).all(),
    }
    return templates.TemplateResponse(
        request,
        "info.html",
        {"data": data, "stocks": stocks, "collection_running": collection_running},
    )


@app.post("/info/{kind}/{item_id}/delete")
def delete_info(kind: str, item_id: int, session: Session = Depends(get_session)):
    model = INFO_MODELS.get(kind)
    if model is not None:
        item = session.get(model, item_id)
        if item is not None:
            session.delete(item)
            session.commit()
    return redirect("/info")


@app.post("/info/{kind}/delete")
def delete_info_batch(kind: str, item_ids: list[int] = Form(default=[]), session: Session = Depends(get_session)):
    model = INFO_MODELS.get(kind)
    if model is not None:
        for item_id in item_ids:
            item = session.get(model, item_id)
            if item is not None:
                session.delete(item)
        session.commit()
    return redirect("/info")


@app.get("/chat", response_class=HTMLResponse)
def chat(request: Request, session_id: int | None = None, session: Session = Depends(get_session)):
    history_sessions = session.exec(select(ChatSession).order_by(col(ChatSession.created_at).desc()).limit(50)).all()
    chat_session = _selected_chat_session(session, session_id, history_sessions)
    messages = []
    if chat_session:
        messages = session.exec(
            select(ChatMessage).where(ChatMessage.session_id == chat_session.id).order_by(ChatMessage.created_at)
        ).all()
    return templates.TemplateResponse(
        request,
        "chat.html",
        {"chat_session": chat_session, "messages": messages, "history_sessions": history_sessions},
    )


@app.post("/chat")
async def ask_chat(
    question: str = Form(...),
    session_id: int | None = Form(None),
    session: Session = Depends(get_session),
):
    chat_session = _selected_chat_session(session, session_id)
    if chat_session is None:
        chat_session = ChatSession()
        session.add(chat_session)
        session.commit()
        session.refresh(chat_session)
    session.add(ChatMessage(session_id=chat_session.id or 0, role="user", content=question))
    answer = await answer_question(session, question)
    session.add(ChatMessage(session_id=chat_session.id or 0, role="assistant", content=answer))
    if _should_update_chat_title(chat_session):
        chat_session.title = await summarize_chat_title(session, question, answer)
        session.add(chat_session)
    session.commit()
    return redirect(f"/chat?session_id={chat_session.id}")


@app.post("/chat/new")
def new_chat(session: Session = Depends(get_session)):
    chat_session = ChatSession()
    session.add(chat_session)
    session.commit()
    session.refresh(chat_session)
    return redirect(f"/chat?session_id={chat_session.id}")


@app.post("/chat/{session_id}/delete")
def delete_chat(session_id: int, session: Session = Depends(get_session)):
    chat_session = session.get(ChatSession, session_id)
    if chat_session is not None:
        messages = session.exec(select(ChatMessage).where(ChatMessage.session_id == session_id)).all()
        for message in messages:
            session.delete(message)
        session.delete(chat_session)
        session.commit()
    return redirect("/chat")


async def summarize_chat_title(session: Session, question: str, answer: str) -> str:
    result = await DeepSeekClient(get_runtime_config(session)).summarize_chat_title(question, answer)
    return result.content or fallback_chat_title(question)


def _should_update_chat_title(chat_session: ChatSession) -> bool:
    title = (chat_session.title or "").strip()
    return not title or title == "新的对话"


def _selected_chat_session(
    session: Session,
    session_id: int | None,
    history_sessions: list[ChatSession] | None = None,
) -> ChatSession | None:
    if session_id is not None:
        selected = session.get(ChatSession, session_id)
        if selected is not None:
            return selected
    if history_sessions is not None:
        return history_sessions[0] if history_sessions else None
    return session.exec(select(ChatSession).order_by(col(ChatSession.created_at).desc()).limit(1)).first()


@app.get("/alerts", response_class=HTMLResponse)
def alerts(request: Request, session: Session = Depends(get_session)):
    stocks = session.exec(select(Stock).order_by(Stock.market, Stock.symbol)).all()
    stock_map = {stock.id: stock for stock in stocks}
    rules = session.exec(select(AlertRule).order_by(col(AlertRule.created_at).desc())).all()
    events = session.exec(select(AlertEvent).order_by(col(AlertEvent.created_at).desc()).limit(30)).all()
    return templates.TemplateResponse(
        request,
        "alerts.html",
        {
            "stocks": stocks,
            "stock_map": stock_map,
            "rules": rules,
            "events": events,
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@app.post("/alerts")
def add_alert(
    stock_id: int = Form(...),
    name: str = Form(""),
    rule_type: str = Form(...),
    threshold: float | None = Form(None),
    keyword: str = Form(""),
    push_mode: str = Form("cooldown"),
    cooldown_minutes: int = Form(30),
    session: Session = Depends(get_session),
):
    normalized_push_mode = push_mode if push_mode in {"cooldown", "once"} else "cooldown"
    normalized_cooldown_minutes = cooldown_minutes if normalized_push_mode == "cooldown" else 30
    session.add(
        AlertRule(
            stock_id=stock_id,
            name=name,
            rule_type=rule_type,
            threshold=threshold,
            keyword=keyword,
            push_mode=normalized_push_mode,
            cooldown_minutes=normalized_cooldown_minutes,
        )
    )
    session.commit()
    return redirect("/alerts")


@app.post("/alerts/{rule_id}/toggle")
def toggle_alert(rule_id: int, session: Session = Depends(get_session)):
    rule = session.get(AlertRule, rule_id)
    if rule:
        rule.enabled = not rule.enabled
        session.add(rule)
        session.commit()
    return redirect("/alerts")


@app.post("/alerts/{rule_id}/delete")
def delete_alert(rule_id: int, session: Session = Depends(get_session)):
    rule = session.get(AlertRule, rule_id)
    if rule:
        session.delete(rule)
        session.commit()
    return redirect("/alerts")


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, session: Session = Depends(get_session)):
    values = all_settings(session)
    masked = values | {
        "deepseek_api_key_masked": mask_secret(values["deepseek_api_key"]),
        "pushdeer_pushkey_masked": mask_secret(values["pushdeer_pushkey"]),
    }
    return templates.TemplateResponse(request, "settings.html", {"settings": masked, "message": ""})


@app.post("/settings")
def save_settings(
    request: Request,
    deepseek_api_key: str = Form(""),
    deepseek_base_url: str = Form(...),
    deepseek_model: str = Form(...),
    pushdeer_pushkey: str = Form(""),
    pushdeer_endpoint: str = Form(...),
    collection_enabled: bool = Form(False),
    market_open_briefs_enabled: bool = Form(False),
    daily_noon_brief_enabled: bool = Form(False),
    daily_noon_brief_time: str = Form(...),
    cn_open_brief_time: str = Form(...),
    us_open_brief_time: str = Form(...),
    session: Session = Depends(get_session),
):
    try:
        cn_open_brief_cron = workday_time_to_cron(cn_open_brief_time)
        us_open_brief_cron = workday_time_to_cron(us_open_brief_time)
        daily_noon_brief_cron = daily_time_to_cron(daily_noon_brief_time)
    except ValueError as exc:
        values = all_settings(session)
        values |= {
            "deepseek_api_key_masked": mask_secret(values["deepseek_api_key"]),
            "pushdeer_pushkey_masked": mask_secret(values["pushdeer_pushkey"]),
        }
        return templates.TemplateResponse(request, "settings.html", {"settings": values, "message": str(exc)})

    if deepseek_api_key.strip():
        set_setting(session, "deepseek_api_key", deepseek_api_key.strip())
    set_setting(session, "deepseek_base_url", deepseek_base_url.strip())
    set_setting(session, "deepseek_model", deepseek_model.strip())
    if pushdeer_pushkey.strip():
        set_setting(session, "pushdeer_pushkey", pushdeer_pushkey.strip())
    set_setting(session, "pushdeer_endpoint", pushdeer_endpoint.strip())
    set_setting(session, "collection_enabled", "true" if collection_enabled else "false")
    set_setting(session, "collect_all_cron", "0 * * * *")
    set_setting(session, "market_open_briefs_enabled", "true" if market_open_briefs_enabled else "false")
    set_setting(session, "daily_noon_brief_enabled", "true" if daily_noon_brief_enabled else "false")
    set_setting(session, "daily_noon_brief_cron", daily_noon_brief_cron)
    set_setting(session, "cn_open_brief_cron", cn_open_brief_cron)
    set_setting(session, "us_open_brief_cron", us_open_brief_cron)
    configure_collection_job(scheduler, collection_enabled, "0 * * * *")
    configure_market_open_brief_jobs(
        scheduler,
        market_open_briefs_enabled,
        cn_open_brief_cron,
        us_open_brief_cron,
    )
    configure_daily_noon_brief_job(scheduler, daily_noon_brief_enabled, daily_noon_brief_cron)
    return redirect("/settings")


@app.post("/settings/test-deepseek", response_class=HTMLResponse)
async def test_deepseek(request: Request, session: Session = Depends(get_session)):
    result = await DeepSeekClient(get_runtime_config(session)).test_connection()
    values = all_settings(session)
    values |= {
        "deepseek_api_key_masked": mask_secret(values["deepseek_api_key"]),
        "pushdeer_pushkey_masked": mask_secret(values["pushdeer_pushkey"]),
    }
    message = "DeepSeek 连接成功" if result.ok else f"DeepSeek 测试失败：{result.error}"
    return templates.TemplateResponse(request, "settings.html", {"settings": values, "message": message})


@app.post("/settings/test-pushdeer", response_class=HTMLResponse)
async def test_pushdeer(request: Request, session: Session = Depends(get_session)):
    result = await PushDeerClient(get_runtime_config(session)).test_push()
    values = all_settings(session)
    values |= {
        "deepseek_api_key_masked": mask_secret(values["deepseek_api_key"]),
        "pushdeer_pushkey_masked": mask_secret(values["pushdeer_pushkey"]),
    }
    return templates.TemplateResponse(request, "settings.html", {"settings": values, "message": result.message})


@app.get("/jobs", response_class=HTMLResponse)
def jobs(request: Request, session: Session = Depends(get_session)):
    items = session.exec(select(FetchJobRun).order_by(col(FetchJobRun.started_at).desc()).limit(50)).all()
    collection_running = is_collection_running(session)
    return templates.TemplateResponse(request, "jobs.html", {"jobs": items, "collection_running": collection_running})


@app.get("/jobs/current")
def current_jobs(job_id: int | None = None, session: Session = Depends(get_session)):
    if job_id is not None:
        job = session.get(FetchJobRun, job_id)
        return {
            "job": _job_payload(job) if job is not None else None,
            "running": [_job_payload(job)] if job is not None and job.status == "running" else [],
            "latest": _job_payload(job) if job is not None else None,
        }
    running = session.exec(
        select(FetchJobRun).where(FetchJobRun.status == "running").order_by(col(FetchJobRun.started_at).desc()).limit(5)
    ).all()
    latest = session.exec(select(FetchJobRun).order_by(col(FetchJobRun.started_at).desc()).limit(1)).first()
    return {
        "running": [_job_payload(item) for item in running],
        "latest": _job_payload(latest) if latest is not None else None,
    }


@app.post("/jobs/run/{job_name}")
async def run_job(job_name: str, request: Request, session: Session = Depends(get_session)):
    redirect_url = request.query_params.get("redirect_url", "/jobs")

    async def action(job_session: Session) -> None:
        if job_name == "quotes":
            await collect_quotes(job_session)
            await push_pending_alert_events(job_session)
        elif job_name == "details":
            await collect_market_details(job_session)
            await push_pending_alert_events(job_session)
        elif job_name == "news":
            await collect_news(job_session)
            await push_pending_alert_events(job_session)
        elif job_name == "announcements":
            await collect_announcements(job_session)
        elif job_name == "macro":
            await collect_macro(job_session)
        elif job_name == "all":
            await collect_all_information(job_session)
            await push_pending_alert_events(job_session)
        elif job_name == "brief":
            await push_pending_alert_events(job_session)
            await generate_daily_brief(job_session, push=False)

    if job_name in {"quotes", "details", "news", "announcements", "macro", "all", "brief"}:
        tracked_name = f"manual_{job_name}"
        if is_progress_request(request):
            run = start_background_job(tracked_name, action, use_collection_lock=is_collection_job_name(tracked_name))
            return {"job_id": run.id, "redirect_url": redirect_url}

        async def inline_action() -> None:
            await action(session)

        await run_tracked_job(session, tracked_name, inline_action, use_collection_lock=is_collection_job_name(tracked_name))
    return redirect(redirect_url)


async def run_tracked_job(session: Session, job_name: str, action, use_collection_lock: bool = True) -> None:
    run = start_job(session, job_name)
    locked = False
    if use_collection_lock and not acquire_collection_job_lock():
        finish_job(session, run, "skipped", "Another collection job is already running.")
        return
    locked = use_collection_lock
    try:
        await action()
        finish_job(session, run, "success")
    except Exception as exc:
        finish_job(session, run, "failed", str(exc))
        raise
    finally:
        if locked:
            release_collection_job_lock()


def _job_payload(job: FetchJobRun) -> dict[str, str | int | None]:
    return {
        "id": job.id,
        "job_name": job.job_name,
        "label": _job_label(job.job_name),
        "status": job.status,
        "started_at": format_beijing_time(job.started_at),
        "ended_at": format_beijing_time(job.ended_at) if job.ended_at else "",
        "error": job.error,
    }


def _job_label(job_name: str) -> str:
    return {
        "manual_brief": "生成并推送 AI 简报",
        "manual_quotes": "抓取行情",
        "manual_details": "抓取交易和盘口信息",
        "manual_news": "抓取新闻",
        "manual_announcements": "抓取公告",
        "manual_macro": "抓取宏观信息",
        "manual_all": "抓取全部信息",
        "collect_all": "定时抓取全部信息",
        "daily_noon_brief": "每日中午24小时简报",
        "quotes": "定时抓取行情",
        "market_details": "定时抓取交易和盘口信息",
        "news": "定时抓取新闻",
        "announcements": "定时抓取公告",
        "macro": "定时抓取宏观信息",
        "cn_open_brief": "A 股/港股开盘后简报",
        "us_open_brief": "美股开盘后简报",
    }.get(job_name, job_name)


def is_progress_request(request: Request) -> bool:
    return request.headers.get("x-progress-request") == "1"


def start_background_job(job_name: str, action, use_collection_lock: bool = True) -> FetchJobRun:
    with Session(engine) as session:
        run = start_job(session, job_name)
        run_id = run.id

    def runner() -> None:
        with Session(engine) as session:
            run = session.get(FetchJobRun, run_id)
            if run is None:
                return
            locked = False
            if use_collection_lock and not acquire_collection_job_lock():
                finish_job(session, run, "skipped", "Another collection job is already running.")
                return
            locked = use_collection_lock
            try:
                asyncio.run(action(session))
                finish_job(session, run, "success")
            except Exception as exc:
                finish_job(session, run, "failed", str(exc))
            finally:
                if locked:
                    release_collection_job_lock()

    Thread(target=runner, name=f"job-{job_name}-{run_id}", daemon=True).start()
    return run


COLLECTION_JOB_NAMES = {
    "collect_all",
    "manual_all",
    "manual_quotes",
    "manual_details",
    "manual_news",
    "manual_announcements",
    "manual_macro",
}


def is_collection_job_name(job_name: str) -> bool:
    return job_name in COLLECTION_JOB_NAMES


def is_collection_running(session: Session) -> bool:
    running = session.exec(select(FetchJobRun).where(FetchJobRun.status == "running")).all()
    return any(is_collection_job_name(job.job_name) for job in running)
