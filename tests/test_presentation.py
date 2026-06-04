from datetime import datetime, timezone

from app.models import Stock
from app.presentation import clean_text, format_beijing_time, replace_stock_refs


def test_format_beijing_time_converts_utc() -> None:
    value = datetime(2026, 6, 4, 0, 5, tzinfo=timezone.utc)

    assert format_beijing_time(value) == "2026-06-04 08:05"


def test_clean_text_strips_html() -> None:
    raw = "<body><p>小米收入增长。</p><p>利润承压。</p></body>"

    assert clean_text(raw) == "小米收入增长。 利润承压。"


def test_replace_stock_refs_with_names() -> None:
    stocks = {
        1: Stock(id=1, market="HK", symbol="1810", name="Xiaomi Corporation"),
        2: Stock(id=2, market="US", symbol="GOOGL", name="Alphabet Inc."),
    }

    text = replace_stock_refs("stock_id=1,2 均录得下跌。", stocks)

    assert "HK 1810 Xiaomi Corporation" in text
    assert "US GOOGL Alphabet Inc." in text
    assert "stock_id=1" not in text
