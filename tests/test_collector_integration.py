from sqlmodel import Session, SQLModel, create_engine, select

from datetime import datetime, timezone

from app.models import (
    AiUsageLog,
    AlertEvent,
    AlertRule,
    HistoricalPrice,
    InstitutionalFlow,
    MarketQuote,
    NewsItem,
    Stock,
    User,
    UserWatchlist,
)
from app.schemas import (
    NormalizedArticle,
    NormalizedInstitutionalFlow,
    NormalizedQuote,
    NormalizedTradingData,
)
from app.services.ai import AiResult
from app.services.collector import (
    build_context,
    collect_market_details,
    collect_news,
    collect_quotes,
    generate_daily_brief,
)
from app.services.content import content_hash

import asyncio


class FakeProvider:
    def fetch_quote(self, market: str, symbol: str) -> NormalizedQuote:
        return NormalizedQuote(
            market=market,
            symbol=symbol,
            price=12.3,
            change_percent=3.2,
            volume=2000,
            volume_ratio=1.6,
            volume_signal="放量",
            source="fake",
        )


class FakeDetailsProvider:
    def fetch_trading_data(self, market: str, symbol: str):
        return None

    def fetch_order_book(self, market: str, symbol: str):
        return None

    def fetch_institutional_flow(
        self, market: str, symbol: str
    ) -> NormalizedInstitutionalFlow:
        return NormalizedInstitutionalFlow(
            symbol=symbol,
            market=market,
            source="fake institutional",
            vwap_proxy=101.2,
            cost_low=99.5,
            cost_high=103.1,
            dark_pool_volume=1000,
            off_exchange_volume=2000,
            sample_days=20,
            raw_data="{}",
        )


class FakeTradingAlertProvider:
    def fetch_trading_data(self, market: str, symbol: str):
        return NormalizedTradingData(
            market=market,
            symbol=symbol,
            price=12,
            change_percent=1,
            volume=5000,
            volume_ratio=0.7,
            volume_signal="缩量",
            source="fake trading",
        )

    def fetch_order_book(self, market: str, symbol: str):
        return None

    def fetch_institutional_flow(self, market: str, symbol: str):
        return None


class CountingNewsProvider:
    def __init__(self, articles=None) -> None:
        self.calls = 0
        self.articles = articles or []

    async def fetch_stock_news(self, stock: Stock):
        self.calls += 1
        return list(self.articles)


class FakeDeepSeekClient:
    last_context = ""

    def __init__(self, config) -> None:
        self.config = config

    async def complete(self, user_prompt: str, context: str = "") -> AiResult:
        FakeDeepSeekClient.last_context = context
        return AiResult(
            True, "简报正文", prompt_tokens=123, completion_tokens=45, total_tokens=168
        )


def test_collect_quotes_triggers_alert() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="AAPL", name="Apple")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        session.add(
            AlertRule(
                stock_id=stock.id or 0,
                rule_type="price_above",
                threshold=10,
                name="price",
            )
        )
        session.commit()

        count = asyncio.run(collect_quotes(session, FakeProvider()))
        event = session.exec(select(AlertEvent)).first()

        assert count == 1
        assert event is not None
        assert "当前价格" in event.message


def test_cloud_collection_uses_active_users_watchlist_union(monkeypatch) -> None:
    import app.services.collector as collector

    monkeypatch.setattr(
        collector, "settings", type("CloudSettings", (), {"app_mode": "api"})()
    )
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        active_user = User(openid="active", status="active")
        pending_user = User(openid="pending", status="pending")
        included = Stock(market="US", symbol="AAPL", name="Apple")
        excluded = Stock(market="US", symbol="MSFT", name="Microsoft")
        session.add_all([active_user, pending_user, included, excluded])
        session.commit()
        session.add(
            UserWatchlist(
                user_id=active_user.id or 0, stock_id=included.id or 0, active=True
            )
        )
        session.add(
            UserWatchlist(
                user_id=pending_user.id or 0, stock_id=excluded.id or 0, active=True
            )
        )
        session.commit()

        count = asyncio.run(collect_quotes(session, FakeProvider()))
        quotes = session.exec(select(MarketQuote)).all()

        assert count == 1
        assert len(quotes) == 1
        assert quotes[0].stock_id == included.id


def test_generate_daily_brief_includes_beijing_time(monkeypatch) -> None:
    import app.services.collector as collector

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 6, 4, 0, 5, tzinfo=timezone.utc)
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(collector, "datetime", FixedDatetime)
    monkeypatch.setattr(collector, "DeepSeekClient", FakeDeepSeekClient)
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        brief = asyncio.run(generate_daily_brief(session))

        assert "北京时间 2026-06-04 08:05" in brief.title
        assert brief.content.startswith("生成时间：北京时间 2026-06-04 08:05")


def test_generate_daily_brief_stores_market_scope(monkeypatch) -> None:
    import app.services.collector as collector

    monkeypatch.setattr(collector, "DeepSeekClient", FakeDeepSeekClient)
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        brief = asyncio.run(generate_daily_brief(session, markets={"US"}))

        assert brief.scope_key == "markets:US"


def test_generate_daily_brief_records_ai_usage(monkeypatch) -> None:
    import app.services.collector as collector

    monkeypatch.setattr(collector, "DeepSeekClient", FakeDeepSeekClient)
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        asyncio.run(generate_daily_brief(session))
        item = session.exec(select(AiUsageLog)).first()

        assert item is not None
        assert item.feature == "brief"
        assert item.prompt_tokens == 123
        assert item.completion_tokens == 45
        assert item.total_tokens == 168


def test_generate_daily_brief_can_limit_context_to_latest_24_hours(monkeypatch) -> None:
    import app.services.collector as collector

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 6, 5, 4, 0, tzinfo=timezone.utc)
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(collector, "datetime", FixedDatetime)
    monkeypatch.setattr(collector, "DeepSeekClient", FakeDeepSeekClient)
    FakeDeepSeekClient.last_context = ""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        session.add(
            MarketQuote(
                stock_id=stock.id or 0,
                price=100,
                source="old-source",
                observed_at=datetime(2026, 6, 4, 3, 59, tzinfo=timezone.utc),
            )
        )
        session.add(
            MarketQuote(
                stock_id=stock.id or 0,
                price=110,
                source="fresh-source",
                observed_at=datetime(2026, 6, 4, 4, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

        asyncio.run(
            generate_daily_brief(session, scope_label="最新24小时", latest_hours=24)
        )

        assert "source=fresh-source" in FakeDeepSeekClient.last_context
        assert "source=old-source" not in FakeDeepSeekClient.last_context


def test_one_time_alert_disables_after_trigger() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="AAPL", name="Apple")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        rule = AlertRule(
            stock_id=stock.id or 0,
            rule_type="price_above",
            threshold=10,
            name="one shot",
            push_mode="once",
        )
        session.add(rule)
        session.commit()
        session.refresh(rule)

        asyncio.run(collect_quotes(session, FakeProvider()))
        updated_rule = session.get(AlertRule, rule.id)
        events = session.exec(select(AlertEvent)).all()

        assert updated_rule is not None
        assert not updated_rule.enabled
        assert len(events) == 1


def test_cooldown_alert_stays_enabled_after_trigger() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="AAPL", name="Apple")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        rule = AlertRule(
            stock_id=stock.id or 0, rule_type="price_above", threshold=10, name="loop"
        )
        session.add(rule)
        session.commit()
        session.refresh(rule)

        asyncio.run(collect_quotes(session, FakeProvider()))
        updated_rule = session.get(AlertRule, rule.id)

        assert updated_rule is not None
        assert updated_rule.enabled


def test_build_context_uses_stock_name_not_raw_stock_id() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="CN", symbol="159501", name="纳指ETF嘉实")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        session.add(MarketQuote(stock_id=stock.id or 0, price=2.1, source="test"))
        session.commit()

        context = build_context(session)

        assert "CN 159501 纳指ETF嘉实" in context
        assert "stock_id=" not in context


def test_build_context_includes_volume_ratio_and_signal() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        session.add(
            MarketQuote(
                stock_id=stock.id or 0,
                price=120,
                volume=2000,
                volume_ratio=1.6,
                volume_signal="放量",
                source="test",
            )
        )
        session.commit()

        context = build_context(session)

        assert "volume_ratio=1.6" in context
        assert "volume_signal=放量" in context


def test_build_context_respects_character_budget() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            NewsItem(
                title="long", source="test", summary="x" * 2000, content_hash="long"
            )
        )
        session.commit()

        context = build_context(session, max_chars=300)

        assert len(context) <= 300
        assert context.endswith("...")


def test_build_context_filters_by_mentioned_stock() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        googl = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        aapl = Stock(market="US", symbol="AAPL", name="Apple Inc.")
        session.add(googl)
        session.add(aapl)
        session.commit()
        session.refresh(googl)
        session.refresh(aapl)
        trade_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        session.add(
            HistoricalPrice(
                stock_id=googl.id or 0,
                trade_date=trade_date,
                close=100,
                content_hash="g",
            )
        )
        session.add(
            HistoricalPrice(
                stock_id=aapl.id or 0,
                trade_date=trade_date,
                close=200,
                content_hash="a",
            )
        )
        session.commit()

        context = build_context(session, query="请获取GOOGL最近一个月的行情数据")

        assert "GOOGL" in context
        assert "AAPL" not in context


def test_build_context_filters_news_by_mentioned_stock() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        googl = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        aapl = Stock(market="US", symbol="AAPL", name="Apple Inc.")
        session.add(googl)
        session.add(aapl)
        session.commit()
        session.refresh(googl)
        session.refresh(aapl)
        session.add(
            NewsItem(
                stock_id=googl.id,
                title="GOOGL volume expands",
                source="test",
                content_hash="g",
            )
        )
        session.add(
            NewsItem(
                stock_id=aapl.id,
                title="Apple volume expands",
                source="test",
                content_hash="a",
            )
        )
        session.commit()

        context = build_context(session, query="请分析GOOGL volume")

        assert "GOOGL volume expands" in context
        assert "Apple volume expands" not in context


def test_build_context_filters_by_market_group() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        hk = Stock(market="HK", symbol="1810", name="Xiaomi")
        cn = Stock(market="CN", symbol="159501", name="纳指ETF嘉实")
        us = Stock(market="US", symbol="NVDA", name="NVIDIA")
        session.add(hk)
        session.add(cn)
        session.add(us)
        session.commit()
        session.refresh(hk)
        session.refresh(cn)
        session.refresh(us)
        session.add(MarketQuote(stock_id=hk.id or 0, price=10, source="test"))
        session.add(MarketQuote(stock_id=cn.id or 0, price=2, source="test"))
        session.add(MarketQuote(stock_id=us.id or 0, price=100, source="test"))
        session.commit()

        cn_hk_context = build_context(session, markets={"CN", "HK"})
        us_context = build_context(session, markets={"US"})

        assert "HK 1810 Xiaomi" in cn_hk_context
        assert "CN 159501 纳指ETF嘉实" in cn_hk_context
        assert "NVDA" not in cn_hk_context
        assert "US NVDA NVIDIA" in us_context
        assert "1810" not in us_context


def test_build_context_prioritizes_new_information_since_cutoff() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="NVDA", name="NVIDIA")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        cutoff = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
        session.add(
            MarketQuote(
                stock_id=stock.id or 0,
                price=100,
                source="old-source",
                observed_at=datetime(2026, 6, 4, 9, 30, tzinfo=timezone.utc),
            )
        )
        session.add(
            MarketQuote(
                stock_id=stock.id or 0,
                price=110,
                source="new-source",
                observed_at=datetime(2026, 6, 4, 10, 30, tzinfo=timezone.utc),
            )
        )
        session.commit()

        context = build_context(session, new_since=cutoff)

        assert "source=new-source" in context
        assert "source=old-source" in context
        assert context.index("source=new-source") < context.index("source=old-source")


def test_collect_market_details_saves_institutional_flow() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        session.add(stock)
        session.commit()
        session.refresh(stock)

        count = asyncio.run(collect_market_details(session, FakeDetailsProvider()))
        item = session.exec(select(InstitutionalFlow)).first()
        context = build_context(session)

        assert count == 1
        assert item is not None
        assert item.vwap_proxy == 101.2
        assert "vwap_proxy=101.2" in context


def test_collect_market_details_can_trigger_volume_alert_from_trading_data() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        session.add(
            AlertRule(
                stock_id=stock.id or 0,
                rule_type="volume_above",
                threshold=1000,
                name="volume",
            )
        )
        session.commit()

        asyncio.run(collect_market_details(session, FakeTradingAlertProvider()))
        event = session.exec(select(AlertEvent)).first()

        assert event is not None
        assert "volume" in event.message


def test_collect_news_skips_recently_collected_stock_news() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        session.add(
            NewsItem(
                stock_id=stock.id,
                title="recent",
                source="test",
                content_hash="recent",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        provider = CountingNewsProvider()

        count = asyncio.run(collect_news(session, provider))

        assert count == 0
        assert provider.calls == 0


def test_collect_news_deduplicates_existing_articles_before_saving() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        session.add(
            NewsItem(
                stock_id=stock.id,
                title="old duplicate",
                source="test",
                url="https://example.com/old",
                content_hash=content_hash(str(stock.id), "https://example.com/old"),
                created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()
        provider = CountingNewsProvider(
            [
                NormalizedArticle(
                    title="old duplicate", source="test", url="https://example.com/old"
                ),
                NormalizedArticle(
                    title="fresh", source="test", url="https://example.com/new"
                ),
            ]
        )

        count = asyncio.run(collect_news(session, provider))
        items = session.exec(select(NewsItem).order_by(NewsItem.url)).all()

        assert count == 1
        assert provider.calls == 1
        assert [item.url for item in items] == [
            "https://example.com/new",
            "https://example.com/old",
        ]


def test_alerts_without_user_are_not_sent_to_external_channels() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        session.add(
            AlertEvent(rule_id=1, stock_id=stock.id or 0, message="legacy alert")
        )
        session.commit()

        from app.services.collector import push_pending_alert_events

        assert asyncio.run(push_pending_alert_events(session)) == 0
