from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, col, select

from app.config import mask_secret, settings
from app.database import get_session, init_db
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
from app.scheduler import build_scheduler
from app.services.ai import DeepSeekClient
from app.services.collector import (
    answer_question,
    collect_all_information,
    collect_announcements,
    collect_macro,
    collect_market_details,
    collect_news,
    collect_quotes,
    generate_daily_brief,
    push_pending_alert_events,
)
from app.services.data_sources import StockIdentityProvider
from app.services.nl_alerts import parse_natural_alert_with_ai
from app.services.pushdeer import PushDeerClient
from app.services.settings_service import all_settings, get_runtime_config, set_setting


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
async def generate_brief(push: bool = Form(False), session: Session = Depends(get_session)):
    await collect_all_information(session)
    await generate_daily_brief(session, push=push)
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
    return templates.TemplateResponse(request, "info.html", {"data": data, "stocks": stocks})


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
def chat(request: Request, session: Session = Depends(get_session)):
    chat_session = session.exec(select(ChatSession).order_by(col(ChatSession.created_at).desc()).limit(1)).first()
    messages = []
    if chat_session:
        messages = session.exec(
            select(ChatMessage).where(ChatMessage.session_id == chat_session.id).order_by(ChatMessage.created_at)
        ).all()
    return templates.TemplateResponse(request, "chat.html", {"chat_session": chat_session, "messages": messages})


@app.post("/chat")
async def ask_chat(question: str = Form(...), session: Session = Depends(get_session)):
    chat_session = session.exec(select(ChatSession).order_by(col(ChatSession.created_at).desc()).limit(1)).first()
    if chat_session is None:
        chat_session = ChatSession(title=question[:80])
        session.add(chat_session)
        session.commit()
        session.refresh(chat_session)
    session.add(ChatMessage(session_id=chat_session.id or 0, role="user", content=question))
    answer = await answer_question(session, question)
    session.add(ChatMessage(session_id=chat_session.id or 0, role="assistant", content=answer))
    session.commit()
    return redirect("/chat")


@app.post("/chat/new")
def new_chat(session: Session = Depends(get_session)):
    session.add(ChatSession())
    session.commit()
    return redirect("/chat")


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
    cooldown_minutes: int = Form(30),
    session: Session = Depends(get_session),
):
    session.add(
        AlertRule(
            stock_id=stock_id,
            name=name,
            rule_type=rule_type,
            threshold=threshold,
            keyword=keyword,
            cooldown_minutes=cooldown_minutes,
        )
    )
    session.commit()
    return redirect("/alerts")


@app.post("/alerts/natural")
async def add_natural_alert(
    description: str = Form(...),
    cooldown_minutes: int = Form(30),
    session: Session = Depends(get_session),
):
    stocks = session.exec(select(Stock).order_by(Stock.market, Stock.symbol)).all()
    result = await parse_natural_alert_with_ai(
        description,
        stocks,
        DeepSeekClient(get_runtime_config(session)),
        cooldown_minutes,
    )
    if not result.ok or result.plan is None:
        query = urlencode({"error": f"AI 未能解析该规则：{result.error}"})
        return redirect(f"/alerts?{query}")
    plan = result.plan
    session.add(
        AlertRule(
            stock_id=plan.stock_id,
            name=plan.name,
            rule_type=plan.rule_type,
            threshold=plan.threshold,
            keyword=plan.keyword,
            cooldown_minutes=plan.cooldown_minutes,
        )
    )
    session.commit()
    query = urlencode({"message": "AI 已根据自然语言描述添加监控规则。"})
    return redirect(f"/alerts?{query}")


@app.post("/alerts/{rule_id}/toggle")
def toggle_alert(rule_id: int, session: Session = Depends(get_session)):
    rule = session.get(AlertRule, rule_id)
    if rule:
        rule.enabled = not rule.enabled
        session.add(rule)
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
    deepseek_api_key: str = Form(""),
    deepseek_base_url: str = Form(...),
    deepseek_model: str = Form(...),
    pushdeer_pushkey: str = Form(""),
    pushdeer_endpoint: str = Form(...),
    session: Session = Depends(get_session),
):
    if deepseek_api_key.strip():
        set_setting(session, "deepseek_api_key", deepseek_api_key.strip())
    set_setting(session, "deepseek_base_url", deepseek_base_url.strip())
    set_setting(session, "deepseek_model", deepseek_model.strip())
    if pushdeer_pushkey.strip():
        set_setting(session, "pushdeer_pushkey", pushdeer_pushkey.strip())
    set_setting(session, "pushdeer_endpoint", pushdeer_endpoint.strip())
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
    return templates.TemplateResponse(request, "jobs.html", {"jobs": items})


@app.post("/jobs/run/{job_name}")
async def run_job(job_name: str, session: Session = Depends(get_session)):
    if job_name == "quotes":
        collect_quotes(session)
        await push_pending_alert_events(session)
    elif job_name == "details":
        collect_market_details(session)
        await push_pending_alert_events(session)
    elif job_name == "news":
        await collect_news(session)
        await push_pending_alert_events(session)
    elif job_name == "announcements":
        await collect_announcements(session)
    elif job_name == "macro":
        await collect_macro(session)
    elif job_name == "all":
        await collect_all_information(session)
        await push_pending_alert_events(session)
    elif job_name == "brief":
        await collect_all_information(session)
        await push_pending_alert_events(session)
        await generate_daily_brief(session, push=False)
    return redirect("/jobs")
