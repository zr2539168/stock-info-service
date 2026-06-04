from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo


CN_TZ = ZoneInfo("Asia/Shanghai")
US_TZ = ZoneInfo("America/New_York")


def is_market_trading_day(market: str, value: datetime | date | None = None) -> bool:
    market = market.upper()
    day = _date_for_market(market, value)
    if day.weekday() >= 5:
        return False
    if market == "CN":
        return _is_cn_trading_day(day)
    if market == "US":
        return _is_us_trading_day(day)
    return True


def market_date(market: str, value: datetime | date | None = None) -> date:
    return _date_for_market(market.upper(), value)


def _date_for_market(market: str, value: datetime | date | None) -> date:
    tz = US_TZ if market == "US" else CN_TZ
    if value is None:
        return datetime.now(tz).date()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)
        return value.astimezone(tz).date()
    return value


def _is_cn_trading_day(day: date) -> bool:
    calendar = _cn_trade_dates(day.year)
    if calendar:
        return day in calendar
    return day.weekday() < 5


@lru_cache(maxsize=8)
def _cn_trade_dates(year: int) -> set[date]:
    try:
        import akshare as ak  # type: ignore

        frame = ak.tool_trade_date_hist_sina()
    except Exception:
        return set()
    result: set[date] = set()
    for value in frame.iloc[:, 0].tolist():
        try:
            parsed = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if parsed.year == year:
            result.add(parsed)
    return result


def _is_us_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in _us_market_holidays(day.year)


@lru_cache(maxsize=8)
def _us_market_holidays(year: int) -> set[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _good_friday(year),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }
    return {item for item in holidays if item.year == year}


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    day = date(year, month, 1)
    offset = (weekday - day.weekday()) % 7
    return day + timedelta(days=offset + 7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    day = date(year + int(month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
    return day - timedelta(days=(day.weekday() - weekday) % 7)


def _good_friday(year: int) -> date:
    return _easter_sunday(year) - timedelta(days=2)


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)
