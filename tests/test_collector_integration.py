from sqlmodel import Session, SQLModel, create_engine, select

from datetime import datetime, timezone

from app.models import AlertEvent, AlertRule, HistoricalPrice, InstitutionalFlow, MarketQuote, Stock
from app.schemas import NormalizedInstitutionalFlow, NormalizedQuote, NormalizedTradingData
from app.services.collector import build_context, collect_market_details, collect_quotes


class FakeProvider:
    def fetch_quote(self, market: str, symbol: str) -> NormalizedQuote:
        return NormalizedQuote(
            market=market,
            symbol=symbol,
            price=12.3,
            change_percent=3.2,
            volume=2000,
            source="fake",
        )


class FakeDetailsProvider:
    def fetch_trading_data(self, market: str, symbol: str):
        return None

    def fetch_order_book(self, market: str, symbol: str):
        return None

    def fetch_institutional_flow(self, market: str, symbol: str) -> NormalizedInstitutionalFlow:
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
            source="fake trading",
        )

    def fetch_order_book(self, market: str, symbol: str):
        return None

    def fetch_institutional_flow(self, market: str, symbol: str):
        return None


def test_collect_quotes_triggers_alert() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="AAPL", name="Apple")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        session.add(AlertRule(stock_id=stock.id or 0, rule_type="price_above", threshold=10, name="price"))
        session.commit()

        count = collect_quotes(session, FakeProvider())
        event = session.exec(select(AlertEvent)).first()

        assert count == 1
        assert event is not None
        assert "当前价格" in event.message


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
        session.add(HistoricalPrice(stock_id=googl.id or 0, trade_date=trade_date, close=100, content_hash="g"))
        session.add(HistoricalPrice(stock_id=aapl.id or 0, trade_date=trade_date, close=200, content_hash="a"))
        session.commit()

        context = build_context(session, query="请获取GOOGL最近一个月的行情数据")

        assert "GOOGL" in context
        assert "AAPL" not in context


def test_collect_market_details_saves_institutional_flow() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        session.add(stock)
        session.commit()
        session.refresh(stock)

        count = collect_market_details(session, FakeDetailsProvider())
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
        session.add(AlertRule(stock_id=stock.id or 0, rule_type="volume_above", threshold=1000, name="volume"))
        session.commit()

        collect_market_details(session, FakeTradingAlertProvider())
        event = session.exec(select(AlertEvent)).first()

        assert event is not None
        assert "volume" in event.message
