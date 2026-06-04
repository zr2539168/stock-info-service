from datetime import date

from app.services.market_calendar import is_market_trading_day


def test_us_market_calendar_skips_independence_day_observed() -> None:
    assert not is_market_trading_day("US", date(2026, 7, 3))


def test_us_market_calendar_accepts_regular_weekday() -> None:
    assert is_market_trading_day("US", date(2026, 7, 6))


def test_cn_market_calendar_skips_weekend() -> None:
    assert not is_market_trading_day("CN", date(2026, 6, 6))
