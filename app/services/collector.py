from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.models import (
    AlertEvent,
    AlertRule,
    Announcement,
    Brief,
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
from app.schemas import NormalizedArticle, NormalizedInstitutionalFlow, NormalizedOrderBook, NormalizedQuote, NormalizedTradingData
from app.presentation import format_beijing_time
from app.services.ai import DeepSeekClient, build_brief_prompt, needs_chinese_translation
from app.services.alerts import alert_message, should_trigger
from app.services.content import compact_text, content_hash
from app.services.data_sources import MarketDataProvider, NewsProvider
from app.services.pushdeer import PushDeerClient
from app.services.settings_service import get_runtime_config
from app.services.nl_fetch import execute_fetch_plan, plan_fetch_from_text


def latest_quote(session: Session, stock_id: int) -> MarketQuote | None:
    return session.exec(
        select(MarketQuote)
        .where(MarketQuote.stock_id == stock_id)
        .order_by(col(MarketQuote.observed_at).desc())
        .limit(1)
    ).first()


def latest_trading_snapshot(session: Session, stock_id: int) -> TradingData | None:
    return session.exec(
        select(TradingData)
        .where(TradingData.stock_id == stock_id)
        .order_by(col(TradingData.observed_at).desc())
        .limit(1)
    ).first()


async def collect_quotes(session: Session, provider: MarketDataProvider | None = None) -> int:
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
    await evaluate_alerts(session)
    return count


async def collect_market_details(session: Session, provider: MarketDataProvider | None = None) -> int:
    provider = provider or MarketDataProvider()
    count = 0
    stocks = session.exec(select(Stock).where(Stock.active == True)).all()  # noqa: E712
    for stock in stocks:
        trading = provider.fetch_trading_data(stock.market, stock.symbol)
        if trading:
            session.add(_trading_to_model(stock.id or 0, trading))
            count += 1
        order_book = provider.fetch_order_book(stock.market, stock.symbol)
        if order_book:
            session.add(_order_book_to_model(stock.id or 0, order_book))
            count += 1
        institutional = provider.fetch_institutional_flow(stock.market, stock.symbol)
        if institutional:
            session.add(_institutional_to_model(stock.id or 0, institutional))
            count += 1
    session.commit()
    await evaluate_alerts(session)
    return count


async def collect_news(session: Session, provider: NewsProvider | None = None) -> int:
    provider = provider or NewsProvider()
    count = 0
    stocks = session.exec(select(Stock).where(Stock.active == True)).all()  # noqa: E712
    for stock in stocks:
        articles = await provider.fetch_stock_news(stock)
        articles = await _translate_articles_to_chinese(session, articles)
        count += _save_articles(session, articles, NewsItem, stock_id=stock.id)
    await evaluate_alerts(session)
    return count


async def collect_announcements(session: Session, provider: NewsProvider | None = None) -> int:
    provider = provider or NewsProvider()
    count = 0
    stocks = session.exec(select(Stock).where(Stock.active == True)).all()  # noqa: E712
    for stock in stocks:
        articles = await provider.fetch_announcements(stock)
        articles = await _translate_articles_to_chinese(session, articles)
        count += _save_articles(session, articles, Announcement, stock_id=stock.id)
    return count


async def collect_macro(session: Session, provider: NewsProvider | None = None) -> int:
    provider = provider or NewsProvider()
    articles = await provider.fetch_macro()
    articles = await _translate_articles_to_chinese(session, articles)
    return _save_articles(session, articles, MacroEvent)


async def collect_all_information(session: Session) -> dict[str, int]:
    return {
        "quotes": await collect_quotes(session),
        "trading_order_book_institutional": await collect_market_details(session),
        "news": await collect_news(session),
        "announcements": await collect_announcements(session),
        "macro": await collect_macro(session),
    }


async def generate_daily_brief(
    session: Session,
    stock_id: int | None = None,
    push: bool = False,
    scope_label: str | None = None,
    markets: set[str] | None = None,
) -> Brief:
    cfg = get_runtime_config(session)
    scope_key = _brief_scope_key(stock_id, markets)
    previous_brief = _latest_brief_for_scope(session, scope_key, stock_id)
    context = build_context(
        session,
        stock_id,
        markets=markets,
        new_since=previous_brief.generated_at if previous_brief else None,
    )
    ai = DeepSeekClient(cfg)
    scope = scope_label or ("自选股" if stock_id is None else "个股")
    result = await ai.complete(build_brief_prompt(scope), context)
    generated_at = datetime.now(timezone.utc)
    generated_time = format_beijing_time(generated_at)
    base_title = f"{scope_label}简报" if scope_label else ("每日市场简报" if stock_id is None else "个股简报")
    title = f"{base_title}（北京时间 {generated_time}）"
    content = f"生成时间：北京时间 {generated_time}\n\n{result.content}"
    brief = Brief(
        stock_id=stock_id,
        scope_key=scope_key,
        title=title,
        content=content,
        sources=context,
        generated_at=generated_at,
    )
    session.add(brief)
    session.commit()
    session.refresh(brief)
    if push:
        await PushDeerClient(cfg).push(title, content)
    return brief


async def answer_question(session: Session, question: str) -> str:
    fetch_note = await maybe_fetch_from_question(session, question)
    cfg = get_runtime_config(session)
    context = build_context(session, None, query=question)
    if fetch_note:
        context = f"{fetch_note}\n{context}"
    result = await DeepSeekClient(cfg).complete(
        f"请回答这个问题：{question}。回答必须引用已有来源；如果资料不足，请明确说明。", context
    )
    return result.content


async def maybe_fetch_from_question(session: Session, question: str) -> str:
    stocks = session.exec(select(Stock)).all()
    plan = plan_fetch_from_text(question, list(stocks))
    if plan is None:
        return ""
    result = execute_fetch_plan(session, plan)
    return f"[自然语言抓取] {result.message}" if result.message else ""


def build_context(
    session: Session,
    stock_id: int | None = None,
    query: str = "",
    markets: set[str] | None = None,
    new_since: datetime | None = None,
) -> str:
    pieces: list[str] = []
    stocks = {stock.id: stock for stock in session.exec(select(Stock)).all()}
    market_stock_ids = [
        item_id
        for item_id, stock in stocks.items()
        if item_id is not None and markets is not None and stock.market.upper() in markets
    ]
    query_stock_ids = _matched_stock_ids(stocks, query) if query else []
    quote_stmt = select(MarketQuote)
    history_stmt = select(HistoricalPrice)
    trading_stmt = select(TradingData)
    order_stmt = select(OrderBookSnapshot)
    institutional_stmt = select(InstitutionalFlow)
    news_stmt = select(NewsItem)
    announcement_stmt = select(Announcement)
    macro_stmt = select(MacroEvent)
    if stock_id is not None:
        quote_stmt = quote_stmt.where(MarketQuote.stock_id == stock_id)
        history_stmt = history_stmt.where(HistoricalPrice.stock_id == stock_id)
        trading_stmt = trading_stmt.where(TradingData.stock_id == stock_id)
        order_stmt = order_stmt.where(OrderBookSnapshot.stock_id == stock_id)
        institutional_stmt = institutional_stmt.where(InstitutionalFlow.stock_id == stock_id)
        news_stmt = news_stmt.where(NewsItem.stock_id == stock_id)
        announcement_stmt = announcement_stmt.where(Announcement.stock_id == stock_id)
    elif markets is not None:
        quote_stmt = quote_stmt.where(MarketQuote.stock_id.in_(market_stock_ids))
        history_stmt = history_stmt.where(HistoricalPrice.stock_id.in_(market_stock_ids))
        trading_stmt = trading_stmt.where(TradingData.stock_id.in_(market_stock_ids))
        order_stmt = order_stmt.where(OrderBookSnapshot.stock_id.in_(market_stock_ids))
        institutional_stmt = institutional_stmt.where(InstitutionalFlow.stock_id.in_(market_stock_ids))
        news_stmt = news_stmt.where(NewsItem.stock_id.in_(market_stock_ids))
        announcement_stmt = announcement_stmt.where(Announcement.stock_id.in_(market_stock_ids))
    elif query_stock_ids:
        quote_stmt = quote_stmt.where(MarketQuote.stock_id.in_(query_stock_ids))
        history_stmt = history_stmt.where(HistoricalPrice.stock_id.in_(query_stock_ids))
        trading_stmt = trading_stmt.where(TradingData.stock_id.in_(query_stock_ids))
        order_stmt = order_stmt.where(OrderBookSnapshot.stock_id.in_(query_stock_ids))
        institutional_stmt = institutional_stmt.where(InstitutionalFlow.stock_id.in_(query_stock_ids))
        news_stmt = news_stmt.where(NewsItem.stock_id.in_(query_stock_ids))
        announcement_stmt = announcement_stmt.where(Announcement.stock_id.in_(query_stock_ids))
    if query:
        like = f"%{query[:40]}%"
        news_stmt = select(NewsItem).where((NewsItem.title.like(like)) | (NewsItem.summary.like(like)))

    for quote in _prioritized_by_time(session, quote_stmt, MarketQuote.observed_at, 20, new_since):
        pieces.append(
            f"[行情] 股票={_stock_label(stocks, quote.stock_id)} price={quote.price} pct={quote.change_percent} "
            f"volume={quote.volume} volume_ratio={quote.volume_ratio} volume_signal={quote.volume_signal} "
            f"source={quote.source} time={quote.observed_at}"
        )
    for price in _prioritized_by_time(session, history_stmt, HistoricalPrice.created_at, 80, new_since):
        pieces.append(
            f"[历史行情] 股票={_stock_label(stocks, price.stock_id)} date={price.trade_date.date()} "
            f"open={price.open} high={price.high} low={price.low} close={price.close} "
            f"volume={price.volume} source={price.source}"
        )
    for trading in _prioritized_by_time(session, trading_stmt, TradingData.observed_at, 20, new_since):
        pieces.append(
            f"[交易数据] 股票={_stock_label(stocks, trading.stock_id)} price={trading.price} pct={trading.change_percent} "
            f"volume={trading.volume} volume_ratio={trading.volume_ratio} volume_signal={trading.volume_signal} "
            f"turnover={trading.turnover} source={trading.source} time={trading.observed_at}"
        )
    for order in _prioritized_by_time(session, order_stmt, OrderBookSnapshot.observed_at, 10, new_since):
        pieces.append(
            f"[盘口] 股票={_stock_label(stocks, order.stock_id)} source={order.source} time={order.observed_at} "
            f"levels={compact_text(order.levels, 420)}"
        )
    for flow in _prioritized_by_time(session, institutional_stmt, InstitutionalFlow.observed_at, 20, new_since):
        pieces.append(
            f"[机构成本/暗池代理] 股票={_stock_label(stocks, flow.stock_id)} "
            f"vwap_proxy={flow.vwap_proxy} cost_band={flow.cost_low}-{flow.cost_high} "
            f"dark_pool_volume={flow.dark_pool_volume} off_exchange_volume={flow.off_exchange_volume} "
            f"sample_days={flow.sample_days} source={flow.source} time={flow.observed_at} "
            f"raw={compact_text(flow.raw_data, 360)}"
        )
    for item in _prioritized_by_time(session, news_stmt, NewsItem.created_at, 20, new_since):
        pieces.append(f"[新闻] 股票={_stock_label(stocks, item.stock_id)} {item.source} {item.title} {compact_text(item.summary, 220)} {item.url}")
    for item in _prioritized_by_time(session, announcement_stmt, Announcement.created_at, 20, new_since):
        pieces.append(f"[公告] 股票={_stock_label(stocks, item.stock_id)} {item.source} {item.title} {compact_text(item.summary, 220)} {item.url}")
    for item in _prioritized_by_time(session, macro_stmt, MacroEvent.created_at, 10, new_since):
        pieces.append(f"[宏观] {item.source} {item.title} {compact_text(item.summary, 220)} {item.url}")
    return "\n".join(pieces) or "暂无本地采集资料。"


def _brief_scope_key(stock_id: int | None, markets: set[str] | None = None) -> str:
    if stock_id is not None:
        return f"stock:{stock_id}"
    if markets:
        return "markets:" + ",".join(sorted(market.upper() for market in markets))
    return "all"


def _latest_brief_for_scope(session: Session, scope_key: str, stock_id: int | None) -> Brief | None:
    brief = session.exec(
        select(Brief).where(Brief.scope_key == scope_key).order_by(col(Brief.generated_at).desc()).limit(1)
    ).first()
    if brief is not None:
        return brief
    legacy_stmt = select(Brief).where(Brief.scope_key == "").order_by(col(Brief.generated_at).desc()).limit(1)
    if scope_key == "all":
        legacy_stmt = legacy_stmt.where(Brief.stock_id == None)  # noqa: E711
    elif stock_id is not None:
        legacy_stmt = legacy_stmt.where(Brief.stock_id == stock_id)
    else:
        return None
    return session.exec(legacy_stmt).first()


def _prioritized_by_time(
    session: Session,
    stmt,
    time_column,
    limit: int,
    new_since: datetime | None,
) -> list:
    if new_since is None:
        return session.exec(stmt.order_by(col(time_column).desc()).limit(limit)).all()

    fresh_items = session.exec(
        stmt.where(time_column > new_since).order_by(col(time_column).desc()).limit(limit)
    ).all()
    remaining = limit - len(fresh_items)
    if remaining <= 0:
        return fresh_items

    fallback_items = session.exec(
        stmt.where(time_column <= new_since).order_by(col(time_column).desc()).limit(remaining)
    ).all()
    return [*fresh_items, *fallback_items]


def _stock_label(stocks: dict[int | None, Stock], stock_id: int | None) -> str:
    stock = stocks.get(stock_id)
    if stock is None:
        return f"未知股票({stock_id})"
    name = f" {stock.name}" if stock.name else ""
    return f"{stock.market} {stock.symbol}{name}"


def _matched_stock_ids(stocks: dict[int | None, Stock], query: str) -> list[int]:
    upper_query = query.upper()
    ids: list[int] = []
    for stock_id, stock in stocks.items():
        if stock_id is None:
            continue
        if stock.symbol.upper() in upper_query or (stock.name and stock.name.upper() in upper_query):
            ids.append(stock_id)
    return ids


async def evaluate_alerts(session: Session) -> list[AlertEvent]:
    events: list[AlertEvent] = []
    rules = session.exec(select(AlertRule).where(AlertRule.enabled == True)).all()  # noqa: E712
    for rule in rules:
        quote = _latest_alert_quote(session, rule.stock_id)
        recent_news = session.exec(
            select(NewsItem)
            .where(NewsItem.stock_id == rule.stock_id)
            .order_by(col(NewsItem.created_at).desc())
            .limit(10)
        ).all()
        if not should_trigger(rule, quote, recent_news):
            continue
        rule.last_triggered_at = datetime.now(timezone.utc)
        if rule.push_mode == "once":
            rule.enabled = False
        if rule.rule_type == "ai_brief":
            await generate_daily_brief(session, stock_id=rule.stock_id, push=True)
            session.add(rule)
        else:
            event = AlertEvent(rule_id=rule.id or 0, stock_id=rule.stock_id, message=alert_message(rule, quote))
            session.add(rule)
            session.add(event)
            events.append(event)
    session.commit()
    return events


async def push_pending_alert_events(session: Session, client: PushDeerClient | None = None) -> int:
    events = session.exec(
        select(AlertEvent).where(AlertEvent.pushed == False).order_by(col(AlertEvent.created_at)).limit(20)  # noqa: E712
    ).all()
    if not events:
        return 0
    pusher = client or PushDeerClient(get_runtime_config(session))
    stocks = {stock.id: stock for stock in session.exec(select(Stock)).all()}
    pushed = 0
    for event in events:
        stock_label = _stock_label(stocks, event.stock_id)
        result = await pusher.push(f"Stock Alert: {stock_label}", f"{stock_label}\n\n{event.message}")
        if not result.ok:
            continue
        event.pushed = True
        session.add(event)
        pushed += 1
    session.commit()
    return pushed


def _latest_alert_quote(session: Session, stock_id: int) -> MarketQuote | None:
    quote = latest_quote(session, stock_id)
    trading = latest_trading_snapshot(session, stock_id)
    if trading is None:
        return quote
    if quote is not None and quote.observed_at >= trading.observed_at:
        return quote
    return MarketQuote(
        stock_id=stock_id,
        price=trading.price,
        change_percent=trading.change_percent,
        volume=trading.volume,
        volume_ratio=trading.volume_ratio,
        volume_signal=trading.volume_signal,
        source=trading.source,
        observed_at=trading.observed_at,
    )


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
        volume_ratio=quote.volume_ratio,
        volume_signal=quote.volume_signal,
        source=quote.source,
    )


def _trading_to_model(stock_id: int, trading: NormalizedTradingData) -> TradingData:
    return TradingData(
        stock_id=stock_id,
        price=trading.price,
        change_percent=trading.change_percent,
        volume=trading.volume,
        volume_ratio=trading.volume_ratio,
        volume_signal=trading.volume_signal,
        turnover=trading.turnover,
        source=trading.source,
        raw_data=trading.raw_data,
    )


def _order_book_to_model(stock_id: int, order_book: NormalizedOrderBook) -> OrderBookSnapshot:
    return OrderBookSnapshot(stock_id=stock_id, source=order_book.source, levels=order_book.levels)


def _institutional_to_model(stock_id: int, flow: NormalizedInstitutionalFlow) -> InstitutionalFlow:
    return InstitutionalFlow(
        stock_id=stock_id,
        source=flow.source,
        vwap_proxy=flow.vwap_proxy,
        cost_low=flow.cost_low,
        cost_high=flow.cost_high,
        dark_pool_volume=flow.dark_pool_volume,
        off_exchange_volume=flow.off_exchange_volume,
        sample_days=flow.sample_days,
        raw_data=flow.raw_data,
    )


async def _translate_articles_to_chinese(session: Session, articles: list[NormalizedArticle]) -> list[NormalizedArticle]:
    if not articles:
        return articles
    cfg = get_runtime_config(session)
    if not cfg.deepseek_api_key:
        return articles
    client = DeepSeekClient(cfg)
    translated_articles: list[NormalizedArticle] = []
    for article in articles:
        if not needs_chinese_translation(article.title, article.summary):
            translated_articles.append(article)
            continue
        result = await client.translate_article_to_chinese(article.title, article.summary)
        if result.ok:
            article.title = result.title
            article.summary = result.summary
        translated_articles.append(article)
    return translated_articles


def _save_articles(
    session: Session,
    articles: list[NormalizedArticle],
    model_type: type[NewsItem] | type[Announcement] | type[MacroEvent],
    stock_id: int | None = None,
) -> int:
    count = 0
    for article in articles:
        digest = content_hash(str(stock_id or ""), article.title, article.url)
        exists = session.exec(select(model_type).where(model_type.content_hash == digest)).first()
        if exists:
            continue
        fields = {
            "source": article.source,
            "title": article.title,
            "url": article.url,
            "summary": compact_text(article.summary, 1500),
            "published_at": article.published_at,
            "content_hash": digest,
        }
        if model_type is not MacroEvent:
            fields["stock_id"] = stock_id
        item = model_type(**fields)
        session.add(item)
        count += 1
    session.commit()
    return count
