from app.models import AlertRule, MarketQuote, NewsItem, Stock
from app.services.ai import AiResult
from app.services.alerts import should_trigger
from app.services.nl_alerts import parse_natural_alert_with_ai

import asyncio


def _u(*codepoints: int) -> str:
    return "".join(chr(codepoint) for codepoint in codepoints)


class FakeAiParser:
    def __init__(self, content: str, ok: bool = True, error: str = "") -> None:
        self.content = content
        self.ok = ok
        self.error = error
        self.user_prompt = ""

    async def complete_json(self, system_prompt: str, user_prompt: str) -> AiResult:
        self.user_prompt = user_prompt
        return AiResult(self.ok, self.content, self.error)


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


def test_parse_natural_price_below_alert() -> None:
    stock = Stock(id=1, market="CN", symbol="159501", name="ETF")
    text = "159501 " + _u(0x4EF7, 0x683C, 0x8DCC, 0x7834) + " 2.1 " + _u(0x63D0, 0x9192)
    ai = FakeAiParser('{"stock_id":1,"rule_type":"price_below","threshold":2.1,"keyword":"","name":"price alert"}')

    result = asyncio.run(parse_natural_alert_with_ai(text, [stock], ai))

    plan = result.plan
    assert result.ok
    assert plan is not None
    assert plan.stock_id == 1
    assert plan.rule_type == "price_below"
    assert plan.threshold == 2.1


def test_parse_natural_pct_alert() -> None:
    stock = Stock(id=2, market="US", symbol="GOOGL", name="Alphabet Inc.")
    text = "GOOGL " + _u(0x6DA8, 0x5E45, 0x8D85, 0x8FC7) + " 5% " + _u(0x63A8, 0x9001)
    ai = FakeAiParser('{"stock_symbol":"GOOGL","rule_type":"pct_change_above","threshold":5,"keyword":"","name":"GOOGL pct"}')

    result = asyncio.run(parse_natural_alert_with_ai(text, [stock], ai))

    plan = result.plan
    assert result.ok
    assert plan is not None
    assert plan.rule_type == "pct_change_above"
    assert plan.threshold == 5


def test_parse_natural_volume_alert_with_unit() -> None:
    stock = Stock(id=3, market="HK", symbol="01810", name="Xiaomi")
    text = "01810 " + _u(0x6210, 0x4EA4, 0x91CF, 0x8D85, 0x8FC7) + " 100" + _u(0x4E07)
    ai = FakeAiParser('{"stock_id":3,"rule_type":"volume_above","threshold":1000000,"keyword":"","name":"volume alert"}')

    result = asyncio.run(parse_natural_alert_with_ai(text, [stock], ai))

    plan = result.plan
    assert result.ok
    assert plan is not None
    assert plan.rule_type == "volume_above"
    assert plan.threshold == 1_000_000


def test_parse_natural_keyword_alert() -> None:
    stock = Stock(id=4, market="HK", symbol="01810", name="Xiaomi")
    text = "Xiaomi " + _u(0x516C, 0x544A, 0x51FA, 0x73B0, 0x56DE, 0x8D2D, 0x65F6, 0x63A8, 0x9001)
    ai = FakeAiParser('{"stock_id":4,"rule_type":"keyword","threshold":null,"keyword":"回购","name":"keyword alert"}')

    result = asyncio.run(parse_natural_alert_with_ai(text, [stock], ai))

    plan = result.plan
    assert result.ok
    assert plan is not None
    assert plan.rule_type == "keyword"
    assert plan.keyword == _u(0x56DE, 0x8D2D)


def test_ai_parser_rejects_unknown_stock() -> None:
    stock = Stock(id=5, market="HK", symbol="01810", name="Xiaomi Corporation")
    ai = FakeAiParser('{"stock_id":999,"rule_type":"keyword","threshold":null,"keyword":"回购","name":"bad"}')

    result = asyncio.run(parse_natural_alert_with_ai("bad request", [stock], ai))

    assert not result.ok
    assert result.plan is None
