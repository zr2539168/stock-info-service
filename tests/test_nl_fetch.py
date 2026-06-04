from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import HistoricalPrice, Stock
from app.schemas import NormalizedHistoricalPrice
from app.services.nl_fetch import execute_fetch_plan, plan_fetch_from_text


class FakeHistoryProvider:
    def fetch_historical_prices(self, market: str, symbol: str, period: str):
        assert market == "US"
        assert symbol == "GOOGL"
        assert period == "1mo"
        return [
            NormalizedHistoricalPrice(
                symbol=symbol,
                market=market,
                trade_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
                open=100,
                high=110,
                low=99,
                close=108,
                volume=123456,
                source="fake history",
            )
        ]


def test_plan_fetch_from_natural_language() -> None:
    stock = Stock(id=1, market="US", symbol="GOOGL", name="Alphabet Inc.")

    plan = plan_fetch_from_text("请获取GOOGL最近一个月的行情数据", [stock])

    assert plan is not None
    assert plan.symbol == "GOOGL"
    assert plan.market == "US"
    assert plan.period == "1mo"


def test_plan_fetch_symbol_without_spaces() -> None:
    plan = plan_fetch_from_text("请获取GOOGL最近一个月的行情数据", [])

    assert plan is not None
    assert plan.symbol == "GOOGL"
    assert plan.market == "US"


def test_execute_fetch_plan_saves_history() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        plan = plan_fetch_from_text("请获取GOOGL最近一个月的行情数据", [stock])
        assert plan is not None

        result = execute_fetch_plan(session, plan, provider=FakeHistoryProvider())
        item = session.exec(select(HistoricalPrice)).first()

        assert result.executed
        assert result.rows_saved == 1
        assert item is not None
        assert item.close == 108
