from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, col, select

from app.config import mask_secret, settings
from app.database import get_session, init_db
from app.models import AlertEvent, AlertRule, Brief, ChatMessage, ChatSession, FetchJobRun, MarketQuote, Stock
from app.scheduler import build_scheduler
from app.services.ai import DeepSeekClient
from app.services.collector import answer_question, collect_macro, collect_news, collect_quotes, generate_daily_brief
from app.services.pushdeer import PushDeerClient
from app.services.settings_service import all_settings, get_runtime_config, set_setting
from app.services.stock_parser import normalize_market, normalize_symbol


templates = Jinja2Templates(directory="app/templates")
scheduler = build_scheduler()


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
    return templates.TemplateResponse(request, "watchlist.html", {"stocks": stocks})


@app.post("/watchlist")
def add_stock(
    market: str = Form(...),
    symbol: str = Form(...),
    name: str = Form(""),
    tags: str = Form(""),
    session: Session = Depends(get_session),
):
    normalized_market = normalize_market(market)
    normalized_symbol = normalize_symbol(symbol, normalized_market)
    existing = session.exec(
        select(Stock).where(Stock.market == normalized_market, Stock.symbol == normalized_symbol)
    ).first()
    if existing:
        existing.name = name or existing.name
        existing.tags = tags
        existing.active = True
        session.add(existing)
    else:
        session.add(Stock(market=normalized_market, symbol=normalized_symbol, name=name, tags=tags))
    session.commit()
    return redirect("/watchlist")


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
    return templates.TemplateResponse(request, "briefs.html", {"briefs": items})


@app.post("/briefs/generate")
async def generate_brief(push: bool = Form(False), session: Session = Depends(get_session)):
    await generate_daily_brief(session, push=push)
    return redirect("/briefs")


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
    rules = session.exec(select(AlertRule).order_by(col(AlertRule.created_at).desc())).all()
    events = session.exec(select(AlertEvent).order_by(col(AlertEvent.created_at).desc()).limit(30)).all()
    return templates.TemplateResponse(request, "alerts.html", {"stocks": stocks, "rules": rules, "events": events})


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
    elif job_name == "news":
        await collect_news(session)
    elif job_name == "macro":
        await collect_macro(session)
    elif job_name == "brief":
        await generate_daily_brief(session, push=False)
    return redirect("/jobs")
