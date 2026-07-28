import asyncio
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.main import app
from app.models import AiUsageLog, MarketIndexAnalysis, MarketIndexPoint
from app.schemas import NormalizedMarketIndex
from app.services.ai import AiResult
from app.services.collector import build_market_index_context, collect_market_indices, generate_market_index_analysis
from app.services.data_sources import CNN_FEAR_GREED_ARCHIVE_URL, MarketIndexProvider


class FakeIndexProvider:
    def __init__(self, value: float = 20.0) -> None:
        self.value = value

    def fetch_indices(self) -> list[NormalizedMarketIndex]:
        return [
            NormalizedMarketIndex(
                code="vix",
                name="标普 500 恐慌指数",
                value=self.value,
                observed_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
                source="fake",
            )
        ]


class FakeDeepSeekClient:
    last_context = ""

    def __init__(self, config) -> None:
        self.config = config

    async def complete(self, user_prompt: str, context: str = "") -> AiResult:
        FakeDeepSeekClient.last_context = context
        return AiResult(True, "股票与债券波动率均有所上升。", prompt_tokens=10, completion_tokens=8, total_tokens=18)


def test_market_index_provider_combines_cnn_and_yfinance(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "fear_and_greed": {
                    "score": 22.5,
                    "rating": "extreme fear",
                    "timestamp": "2026-07-28T07:49:01+00:00",
                },
                "fear_and_greed_historical": {
                    "data": [{"x": 1785110400000, "y": 24.0, "rating": "extreme fear"}]
                },
            }

    dates = pd.DatetimeIndex([datetime(2026, 7, 27, tzinfo=timezone.utc)])
    values = {"^VIX": 19.2, "^MOVE": 77.1, "^TNX": 4.64}

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, **_kwargs):
            return pd.DataFrame([{"Close": values[self.symbol]}], index=dates)

    monkeypatch.setattr("app.services.data_sources.httpx.get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=FakeTicker))

    points = MarketIndexProvider().fetch_indices()

    assert {point.code for point in points} == {"fear_greed", "vix", "move", "us10y"}
    latest_fear_greed = [point for point in points if point.code == "fear_greed"][-1]
    assert latest_fear_greed.value == 22.5
    assert latest_fear_greed.status == "极度恐惧"
    assert next(point for point in points if point.code == "us10y").unit == "%"


def test_market_index_provider_can_fetch_full_history(monkeypatch) -> None:
    requested_periods = []

    class FakeResponse:
        def __init__(self, archive: bool = False) -> None:
            self.archive = archive
            self.text = "Date,Fear Greed,Rating\n2011-01-03,68.0,greed\n"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "fear_and_greed": {
                    "score": 40.0,
                    "rating": "fear",
                    "timestamp": "2026-07-28T08:00:00+00:00",
                },
                "fear_and_greed_historical": {"data": []},
            }

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, **kwargs):
            requested_periods.append(kwargs["period"])
            return pd.DataFrame(
                [{"Close": 20.0}],
                index=pd.DatetimeIndex([datetime(1990, 1, 2, tzinfo=timezone.utc)]),
            )

    def fake_get(url, **_kwargs):
        return FakeResponse(archive=url == CNN_FEAR_GREED_ARCHIVE_URL)

    monkeypatch.setattr("app.services.data_sources.httpx.get", fake_get)
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=FakeTicker))

    points = MarketIndexProvider().fetch_indices(full_history=True)

    fear_dates = [point.observed_at.date().isoformat() for point in points if point.code == "fear_greed"]
    assert "2011-01-03" in fear_dates
    assert "max" in requested_periods


def test_collect_market_indices_upserts_same_observation() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        assert asyncio.run(collect_market_indices(session, FakeIndexProvider(20.0))) == 1
        assert asyncio.run(collect_market_indices(session, FakeIndexProvider(20.0))) == 0
        assert asyncio.run(collect_market_indices(session, FakeIndexProvider(21.5))) == 1
        points = session.exec(select(MarketIndexPoint)).all()

        assert len(points) == 1
        assert points[0].value == 21.5


def test_collect_market_indices_keeps_one_latest_point_per_day() -> None:
    class IntradayProvider:
        def __init__(self, hour: int, value: float) -> None:
            self.hour = hour
            self.value = value

        def fetch_indices(self) -> list[NormalizedMarketIndex]:
            return [
                NormalizedMarketIndex(
                    code="fear_greed",
                    name="恐贪指数",
                    value=self.value,
                    observed_at=datetime(2026, 7, 28, self.hour, tzinfo=timezone.utc),
                    source="CNN",
                )
            ]

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        asyncio.run(collect_market_indices(session, IntradayProvider(1, 40.0)))
        asyncio.run(collect_market_indices(session, IntradayProvider(8, 41.0)))
        points = session.exec(select(MarketIndexPoint)).all()

    assert len(points) == 1
    assert points[0].value == 41.0
    assert points[0].observed_at.hour == 8


def test_collect_market_indices_only_requests_full_history_until_backfilled(monkeypatch) -> None:
    import app.services.collector as collector

    requested = []

    class FullHistoryProvider:
        def fetch_indices(self, full_history: bool = False) -> list[NormalizedMarketIndex]:
            requested.append(full_history)
            dates = {
                "fear_greed": datetime(2011, 1, 3, tzinfo=timezone.utc),
                "vix": datetime(1990, 1, 2, tzinfo=timezone.utc),
                "move": datetime(2002, 11, 12, tzinfo=timezone.utc),
                "us10y": datetime(1962, 1, 2, tzinfo=timezone.utc),
            }
            return [
                NormalizedMarketIndex(code=code, name=code, value=20.0, observed_at=observed_at)
                for code, observed_at in dates.items()
            ]

    monkeypatch.setattr(collector, "MarketIndexProvider", FullHistoryProvider)
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        asyncio.run(collect_market_indices(session))
        asyncio.run(collect_market_indices(session))

    assert requested == [True, False]


def test_market_index_context_contains_historical_changes() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)

    with Session(engine) as session:
        for day in range(40):
            observed_at = start + timedelta(days=day)
            session.add(
                MarketIndexPoint(
                    index_code="vix",
                    name="标普 500 恐慌指数",
                    value=15 + day / 10,
                    source="fake",
                    observed_at=observed_at,
                    content_hash=f"vix-{day}",
                )
            )
        session.commit()

        context = build_market_index_context(session)

    assert "VIX / 标普 500 恐慌指数" in context
    assert "7日前=" in context
    assert "30日前=" in context
    assert "最近30个交易日=" in context
    assert "Fear & Greed Index / 恐贪指数] 暂无数据" in context


def test_generate_market_index_analysis_records_result_and_usage(monkeypatch) -> None:
    import app.services.collector as collector

    monkeypatch.setattr(collector, "DeepSeekClient", FakeDeepSeekClient)
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        asyncio.run(collect_market_indices(session, FakeIndexProvider()))
        result = asyncio.run(generate_market_index_analysis(session))
        usage = session.exec(select(AiUsageLog)).first()
        stored = session.exec(select(MarketIndexAnalysis)).first()

    assert result.content == "股票与债券波动率均有所上升。"
    assert stored is not None
    assert usage is not None
    assert usage.feature == "market_indices"
    assert usage.total_tokens == 18
    assert "VIX" in FakeDeepSeekClient.last_context


def test_indices_page_renders_latest_values_charts_and_actions() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            MarketIndexPoint(
                index_code="vix",
                name="标普 500 恐慌指数",
                value=19.12,
                source="fake",
                observed_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
                content_hash="vix-latest",
            )
        )
        session.add(
            MarketIndexPoint(
                index_code="vix",
                name="标普 500 恐慌指数",
                value=17.5,
                source="fake",
                observed_at=datetime(2010, 7, 28, tzinfo=timezone.utc),
                content_hash="vix-oldest",
            )
        )
        session.commit()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.get("/indices")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    assert 'href="/indices">指数</a>' in response.text
    assert "19.12" in response.text
    assert 'data-index-chart="index-series-vix"' in response.text
    assert "2010-07-28" in response.text
    for value in ("7d", "30d", "1y", "10y", "max"):
        assert f'data-index-range="{value}"' in response.text
    assert "/static/styles.css?v=" in response.text
    assert "/static/app.js?v=" in response.text
    assert "/jobs/run/indices?redirect_url=/indices" in response.text
    assert 'action="/indices/analyze"' in response.text
