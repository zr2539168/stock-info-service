from app.services.stock_parser import normalize_market, normalize_symbol, to_yfinance_symbol


def test_normalize_cn_aliases() -> None:
    assert normalize_market("A股") == "CN"
    assert normalize_market("us") == "US"
    assert normalize_market("港股") == "HK"


def test_hk_symbol_padding() -> None:
    assert normalize_symbol("700", "HK") == "0700"
    assert to_yfinance_symbol("700", "HK") == "0700.HK"


def test_hk_symbol_strips_mainland_style_leading_zero() -> None:
    assert normalize_symbol("01810", "HK") == "1810"
    assert to_yfinance_symbol("01810", "HK") == "1810.HK"


def test_cn_yfinance_suffix() -> None:
    assert to_yfinance_symbol("600519", "CN") == "600519.SS"
    assert to_yfinance_symbol("000001", "CN") == "000001.SZ"
