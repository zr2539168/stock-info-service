from app.models import AlertRule, MarketQuote, NewsItem
from app.services.alerts import should_trigger


def _u(*codepoints: int) -> str:
    return "".join(chr(codepoint) for codepoint in codepoints)


def test_price_alert_triggers() -> None:
    rule = AlertRule(stock_id=1, rule_type="price_above", threshold=10)
    quote = MarketQuote(stock_id=1, price=11)
    assert should_trigger(rule, quote)


def test_volume_alert_does_not_trigger_below_threshold() -> None:
    rule = AlertRule(stock_id=1, rule_type="volume_above", threshold=1000)
    quote = MarketQuote(stock_id=1, volume=999)
    assert not should_trigger(rule, quote)


def test_keyword_alert_matches_news() -> None:
    keyword = _u(0x56DE, 0x8D2D)
    rule = AlertRule(stock_id=1, rule_type="keyword", keyword=keyword)
    news = [NewsItem(stock_id=1, title=_u(0x516C, 0x53F8, 0x5BA3, 0x5E03, 0x56DE, 0x8D2D, 0x8BA1, 0x5212), content_hash="a")]
    assert should_trigger(rule, None, news)
