from sqlmodel import Session, SQLModel, create_engine, select

from app.models import AlertEvent, AlertRule, MarketQuote, Stock
from app.schemas import NormalizedQuote
from app.services.collector import build_context, collect_quotes


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
