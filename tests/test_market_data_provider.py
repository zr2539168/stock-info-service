import sys
from types import SimpleNamespace

import pandas as pd

from app.services.data_sources import MarketDataProvider


def test_cn_quote_falls_back_to_etf_spot(monkeypatch) -> None:
    fake_akshare = SimpleNamespace(
        stock_zh_a_spot_em=lambda: pd.DataFrame(
            [{"代码": "600519", "名称": "贵州茅台", "最新价": 1500.0}]
        ),
        fund_etf_spot_em=lambda: pd.DataFrame(
            [
                {
                    "代码": "159501",
                    "名称": "纳指ETF嘉实",
                    "最新价": 2.107,
                    "开盘价": 2.12,
                    "最高价": 2.131,
                    "最低价": 2.104,
                    "昨收": 2.153,
                    "涨跌幅": -2.14,
                    "成交量": 1149889,
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
                    "代码": "159501",
                    "名称": "纳指ETF嘉实",
                    "最新价": 2.107,
                    "开盘价": 2.12,
                    "最高价": 2.131,
                    "最低价": 2.104,
                    "昨收": 2.153,
                    "涨跌幅": -2.14,
                    "成交量": 1149889,
                }
            ]
        ),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    quote = MarketDataProvider().fetch_quote("CN", "159501")

    assert quote is not None
    assert quote.source == "AKShare ETF"
