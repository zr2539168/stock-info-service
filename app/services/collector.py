from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.models import (
    AlertEvent,
    AlertRule,
    Brief,
    FetchJobRun,
    MacroEvent,
    MarketQuote,
    NewsItem,
    Stock,
)
from app.schemas import NormalizedArticle, NormalizedQuote
from app.services.ai import DeepSeekClient, build_brief_prompt
from app.services.alerts import alert_message, should_trigger
from app.services.content import compact_text, content_hash
from app.services.data_sources import MarketDataProvider, NewsProvider
from app.services.pushdeer import PushDeerClient
from app.services.settings_service import get_runtime_config


def latest_quote(session: Session, stock_id: int) -> MarketQuote | None:
    return session.exec(
        select(MarketQuote)
        .where(MarketQuote.stock_id == stock_id)
        .order_by(col(MarketQuote.observed_at).desc())
        .limit(1)
    ).first()


def collect_quotes(session: Session, provider: MarketDataProvider | None = None) -> int:
    provider = provider or MarketDataProvider()
    count = 0
    stocks = session.exec(select(Stock).where(Stock.active == True)).all()  # noqa: E712
    for stock in stocks:
        quote = provider.fetch_quote(stock.market, stock.symbol)
        if quote is None:
            continue
        session.add(_quote_to_model(stock.id or 0, quote))
        count += 1
    session.commit()
    evaluate_alerts(session)
    return count


async def collect_news(session: Session, provider: NewsProvider | None = None) -> int:
    provider = provider or NewsProvider()
    articles = await provider.fetch_news()
    count = _save_articles(session, articles, NewsItem)
    evaluate_alerts(session)
    return count


async def collect_macro(session: Session, provider: NewsProvider | None = None) -> int:
    provider = provider or NewsProvider()
    articles = await provider.fetch_macro()
    return _save_articles(session, articles, MacroEvent)


async def generate_daily_brief(session: Session, stock_id: int | None = None, push: bool = False) -> Brief:
    cfg = get_runtime_config(session)
    context = build_context(session, stock_id)
    ai = DeepSeekClient(cfg)
    scope = "自选股" if stock_id is None else "个股"
    result = await ai.complete(build_brief_prompt(scope), context)
    title = "每日市场简报" if stock_id is None else "个股简报"
    brief = Brief(stock_id=stock_id, title=title, content=result.content, sources=context)
    session.add(brief)
    session.commit()
    session.refresh(brief)
    if push:
        await PushDeerClient(cfg).push(title, result.content)
    return brief


async def answer_question(session: Session, question: str) -> str:
    cfg = get_runtime_config(session)
    context = build_context(session, None, query=question)
    result = await DeepSeekClient(cfg).complete(
        f"请回答这个问题：{question}。回答必须引用已有来源；如果资料不足，请明确说明。", context
    )
    return result.content


def build_context(session: Session, stock_id: int | None = None, query: str = "") -> str:
    pieces: list[str] = []
    quote_stmt = select(MarketQuote).order_by(col(MarketQuote.observed_at).desc()).limit(20)
    news_stmt = select(NewsItem).order_by(col(NewsItem.created_at).desc()).limit(20)
    macro_stmt = select(MacroEvent).order_by(col(MacroEvent.created_at).desc()).limit(10)
    if stock_id is not None:
        quote_stmt = quote_stmt.where(MarketQuote.stock_id == stock_id)
        news_stmt = news_stmt.where(NewsItem.stock_id == stock_id)
    if query:
        like = f"%{query[:40]}%"
        news_stmt = select(NewsItem).where((NewsItem.title.like(like)) | (NewsItem.summary.like(like))).limit(20)

    for quote in session.exec(quote_stmt).all():
        pieces.append(
            f"[行情] stock_id={quote.stock_id} price={quote.price} pct={quote.change_percent} "
            f"volume={quote.volume} source={quote.source} time={quote.observed_at}"
        )
    for item in session.exec(news_stmt).all():
        pieces.append(f"[新闻] {item.source} {item.title} {compact_text(item.summary, 220)} {item.url}")
    for item in session.exec(macro_stmt).all():
        pieces.append(f"[宏观] {item.source} {item.title} {compact_text(item.summary, 220)} {item.url}")
    return "\n".join(pieces) or "暂无本地采集资料。"


def evaluate_alerts(session: Session) -> list[AlertEvent]:
    events: list[AlertEvent] = []
    rules = session.exec(select(AlertRule).where(AlertRule.enabled == True)).all()  # noqa: E712
    for rule in rules:
        quote = latest_quote(session, rule.stock_id)
        recent_news = session.exec(
            select(NewsItem)
            .where(NewsItem.stock_id == rule.stock_id)
            .order_by(col(NewsItem.created_at).desc())
            .limit(10)
        ).all()
        if should_trigger(rule, quote, recent_news):
            rule.last_triggered_at = datetime.now(timezone.utc)
            event = AlertEvent(rule_id=rule.id or 0, stock_id=rule.stock_id, message=alert_message(rule, quote))
            session.add(rule)
            session.add(event)
            events.append(event)
    session.commit()
    return events


def start_job(session: Session, name: str) -> FetchJobRun:
    run = FetchJobRun(job_name=name, status="running")
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def finish_job(session: Session, run: FetchJobRun, status: str, error: str = "") -> None:
    run.status = status
    run.error = error
    run.ended_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()


def _quote_to_model(stock_id: int, quote: NormalizedQuote) -> MarketQuote:
    return MarketQuote(
        stock_id=stock_id,
        price=quote.price,
        open=quote.open,
        high=quote.high,
        low=quote.low,
        previous_close=quote.previous_close,
        change_percent=quote.change_percent,
        volume=quote.volume,
        source=quote.source,
    )


def _save_articles(session: Session, articles: list[NormalizedArticle], model_type: type[NewsItem] | type[MacroEvent]) -> int:
    count = 0
    for article in articles:
        digest = content_hash(article.title, article.url)
        exists = session.exec(select(model_type).where(model_type.content_hash == digest)).first()
        if exists:
            continue
        item = model_type(
            source=article.source,
            title=article.title,
            url=article.url,
            summary=compact_text(article.summary, 1500),
            published_at=article.published_at,
            content_hash=digest,
        )
        session.add(item)
        count += 1
    session.commit()
    return count

