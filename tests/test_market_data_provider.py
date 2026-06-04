import sys
from types import SimpleNamespace

import pandas as pd

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
