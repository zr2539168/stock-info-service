import sys
from types import SimpleNamespace
from datetime import datetime, timezone

import pandas as pd

from app.schemas import NormalizedHistoricalPrice
from app.services.data_sources import (
    COL_CHANGE_PERCENT,
    COL_CODE,
    COL_HIGH_ETF,
    COL_LOW_ETF,
    COL_NAME,
    COL_OPEN_ETF,
    COL_PREV_CLOSE,
    COL_PRICE,
    COL_VOLUME,
    MarketDataProvider,
    _institutional_cost_proxy,
    _summarize_finra_rows,
)


def test_cn_quote_falls_back_to_etf_spot(monkeypatch) -> None:
    fake_akshare = SimpleNamespace(
        stock_zh_a_spot_em=lambda: pd.DataFrame(
            [{COL_CODE: "600519", COL_NAME: "贵州茅台", COL_PRICE: 1500.0}]
        ),
        fund_etf_spot_em=lambda: pd.DataFrame(
            [
                {
                    COL_CODE: "159501",
                    COL_NAME: "纳指ETF嘉实",
                    COL_PRICE: 2.107,
                    COL_OPEN_ETF: 2.12,
                    COL_HIGH_ETF: 2.131,
                    COL_LOW_ETF: 2.104,
                    COL_PREV_CLOSE: 2.153,
                    COL_CHANGE_PERCENT: -2.14,
                    COL_VOLUME: 1149889,
                }
            ]
        ),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    quote = MarketDataProvider().fetch_quote("CN", "159501")

    assert quote is not None
    assert quote.symbol == "159501"
    assert quote.price == 2.107
    assert quote.open == 2.12
    assert quote.source == "AKShare ETF"


def test_cn_quote_tries_etf_when_stock_spot_fails(monkeypatch) -> None:
    fake_akshare = SimpleNamespace(
        stock_zh_a_spot_em=lambda: (_ for _ in ()).throw(RuntimeError("stock source unavailable")),
        fund_etf_spot_em=lambda: pd.DataFrame(
            [
                {
                    COL_CODE: "159501",
                    COL_NAME: "纳指ETF嘉实",
                    COL_PRICE: 2.107,
                    COL_OPEN_ETF: 2.12,
                    COL_HIGH_ETF: 2.131,
                    COL_LOW_ETF: 2.104,
                    COL_PREV_CLOSE: 2.153,
                    COL_CHANGE_PERCENT: -2.14,
                    COL_VOLUME: 1149889,
                }
            ]
        ),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    quote = MarketDataProvider().fetch_quote("CN", "159501")

    assert quote is not None
    assert quote.source == "AKShare ETF"


def test_institutional_cost_proxy_uses_volume_weighted_price() -> None:
    history = [
        NormalizedHistoricalPrice("GOOGL", "US", datetime(2026, 6, 1, tzinfo=timezone.utc), close=100, volume=100),
        NormalizedHistoricalPrice("GOOGL", "US", datetime(2026, 6, 2, tzinfo=timezone.utc), close=110, volume=300),
    ]

    result = _institutional_cost_proxy(history)

    assert result["vwap_proxy"] == 107.5
    assert result["sample_days"] == 2
    assert result["cost_low"] < result["vwap_proxy"] < result["cost_high"]


def test_finra_summary_aggregates_ats_and_non_ats_volume() -> None:
    rows = [
        {"summaryType": "ATS", "totalWeeklyShareQuantity": 1000, "weekStartDate": "2026-05-01"},
        {"summaryType": "Non-ATS", "totalWeeklyShareQuantity": 3000, "weekStartDate": "2026-05-01"},
    ]

    result = _summarize_finra_rows(rows)

    assert result["ats_volume"] == 1000
    assert result["non_ats_volume"] == 3000
