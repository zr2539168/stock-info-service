import sys
from types import SimpleNamespace

import pandas as pd

from app.services.data_sources import StockIdentityProvider


def test_resolve_cn_stock_uses_akshare_name(monkeypatch) -> None:
    fake_akshare = SimpleNamespace(
        stock_zh_a_spot_em=lambda: pd.DataFrame(
            [
                {"代码": "600519", "名称": "贵州茅台"},
                {"代码": "000001", "名称": "平安银行"},
            ]
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    resolved = StockIdentityProvider().resolve("A股", "600519")

    assert resolved is not None
    assert resolved.market == "CN"
    assert resolved.symbol == "600519"
    assert resolved.name == "贵州茅台"


def test_resolve_cn_rejects_non_numeric_symbol_without_yfinance_fallback(monkeypatch) -> None:
    fake_yfinance = SimpleNamespace(Ticker=lambda symbol: (_ for _ in ()).throw(AssertionError("should not call yfinance")))
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    assert StockIdentityProvider().resolve("CN", "QQQ") is None


def test_resolve_cn_stock_returns_none_for_unknown_code(monkeypatch) -> None:
    fake_akshare = SimpleNamespace(stock_zh_a_spot_em=lambda: pd.DataFrame([{"代码": "600519", "名称": "贵州茅台"}]))
    fake_yfinance = SimpleNamespace(Ticker=lambda symbol: (_ for _ in ()).throw(RuntimeError("not found")))
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    assert StockIdentityProvider().resolve("CN", "999999") is None


def test_resolve_cn_etf_uses_akshare_etf_name(monkeypatch) -> None:
    fake_akshare = SimpleNamespace(
        stock_zh_a_spot_em=lambda: pd.DataFrame([{"代码": "600519", "名称": "贵州茅台"}]),
        fund_etf_spot_em=lambda: pd.DataFrame([{"代码": "159501", "名称": "纳指ETF嘉实"}]),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    resolved = StockIdentityProvider().resolve("CN", "159501")

    assert resolved is not None
    assert resolved.market == "CN"
    assert resolved.symbol == "159501"
    assert resolved.name == "纳指ETF嘉实"


def test_resolve_hk_stock_normalizes_01810_to_yfinance_symbol(monkeypatch) -> None:
    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def get_info(self) -> dict[str, str]:
            assert self.symbol == "1810.HK"
            return {"longName": "Xiaomi Corporation"}

    fake_yfinance = SimpleNamespace(Ticker=FakeTicker)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    resolved = StockIdentityProvider().resolve("HK", "01810")

    assert resolved is not None
    assert resolved.market == "HK"
    assert resolved.symbol == "1810"
    assert resolved.name == "Xiaomi Corporation"


def test_resolve_us_stock_uses_yfinance_name(monkeypatch) -> None:
    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def get_info(self) -> dict[str, str]:
            assert self.symbol == "AAPL"
            return {"longName": "Apple Inc."}

    fake_yfinance = SimpleNamespace(Ticker=FakeTicker)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    resolved = StockIdentityProvider().resolve("US", "aapl")

    assert resolved is not None
    assert resolved.market == "US"
    assert resolved.symbol == "AAPL"
    assert resolved.name == "Apple Inc."


def test_local_only_resolver_accepts_valid_symbols_without_remote_calls(monkeypatch) -> None:
    fake_akshare = SimpleNamespace(
        stock_zh_a_spot_em=lambda: (_ for _ in ()).throw(AssertionError("should not call AKShare"))
    )
    fake_yfinance = SimpleNamespace(
        Ticker=lambda symbol: (_ for _ in ()).throw(AssertionError("should not call yfinance"))
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)
    provider = StockIdentityProvider(remote_lookup=False)

    cn = provider.resolve("CN", "159501")
    us = provider.resolve("US", "googl")

    assert cn is not None and (cn.market, cn.symbol, cn.name) == ("CN", "159501", "159501")
    assert us is not None and (us.market, us.symbol, us.name) == ("US", "GOOGL", "GOOGL")


def test_local_only_resolver_rejects_invalid_market_and_symbol_formats() -> None:
    provider = StockIdentityProvider(remote_lookup=False)

    assert provider.resolve("CN", "QQQ") is None
    assert provider.resolve("HK", "0700A") is None
    assert provider.resolve("US", "GOOGL$") is None
    assert provider.resolve("UNKNOWN", "AAPL") is None
