from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from xml.etree import ElementTree

import httpx

from app.models import Stock
from app.schemas import (
    NormalizedArticle,
    NormalizedHistoricalPrice,
    NormalizedInstitutionalFlow,
    NormalizedMarketIndex,
    NormalizedOrderBook,
    NormalizedQuote,
    NormalizedTradingData,
    ResolvedStock,
)
from app.services.stock_parser import normalize_market, normalize_symbol, to_yfinance_symbol


DEFAULT_NEWS_FEEDS = [
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("SEC Latest Filings", "https://www.sec.gov/news/pressreleases.rss"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
]

DEFAULT_MACRO_FEEDS = [
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("SEC Latest Filings", "https://www.sec.gov/news/pressreleases.rss"),
]


@dataclass(frozen=True)
class MarketIndexDefinition:
    code: str
    name: str
    symbol: str
    unit: str
    description: str
    source: str
    source_url: str


MARKET_INDEX_DEFINITIONS = (
    MarketIndexDefinition(
        code="fear_greed",
        name="恐贪指数",
        symbol="Fear & Greed Index",
        unit="",
        description="CNN 综合市场动量、强弱、波动率、避险需求等七项指标形成的 0–100 市场情绪分数。数值越低越恐惧，越高越贪婪。",
        source="CNN",
        source_url="https://www.cnn.com/markets/fear-and-greed",
    ),
    MarketIndexDefinition(
        code="vix",
        name="标普 500 恐慌指数",
        symbol="VIX",
        unit="",
        description="基于标普 500 指数期权价格计算的未来 30 天预期波动率。通常数值快速上升代表股票市场避险情绪增强。",
        source="Yahoo Finance / Cboe",
        source_url="https://www.cboe.com/tradable_products/vix/",
    ),
    MarketIndexDefinition(
        code="move",
        name="债券市场恐慌指数",
        symbol="MOVE",
        unit="",
        description="衡量美国国债期权隐含波动率的指标，常被称为债券市场的 VIX。数值上升通常代表利率和债券市场不确定性增加。",
        source="Yahoo Finance / ICE BofA",
        source_url="https://finance.yahoo.com/quote/%5EMOVE/",
    ),
    MarketIndexDefinition(
        code="us10y",
        name="美国 10 年期国债收益率",
        symbol="10Y Treasury",
        unit="%",
        description="美国 10 年期国债市场收益率，是全球资产定价和长期融资成本的重要参考。上升通常意味着长期利率环境趋紧。",
        source="Yahoo Finance / U.S. Treasury",
        source_url="https://home.treasury.gov/resource-center/data-chart-center/interest-rates/",
    ),
)

YFINANCE_INDEX_SYMBOLS = {
    "vix": "^VIX",
    "move": "^MOVE",
    "us10y": "^TNX",
}

CNN_FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_FEAR_GREED_ARCHIVE_URL = "https://raw.githubusercontent.com/whit3rabbit/fear-greed-data/main/fear-greed.csv"
CNN_FEAR_GREED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
    "Origin": "https://www.cnn.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

def _u(*codes: int) -> str:
    return "".join(chr(code) for code in codes)


COL_CODE = _u(0x4EE3, 0x7801)
COL_NAME = _u(0x540D, 0x79F0)
COL_PRICE = _u(0x6700, 0x65B0, 0x4EF7)
COL_OPEN = _u(0x4ECA, 0x5F00)
COL_OPEN_ETF = _u(0x5F00, 0x76D8, 0x4EF7)
COL_HIGH = _u(0x6700, 0x9AD8)
COL_HIGH_ETF = _u(0x6700, 0x9AD8, 0x4EF7)
COL_LOW = _u(0x6700, 0x4F4E)
COL_LOW_ETF = _u(0x6700, 0x4F4E, 0x4EF7)
COL_PREV_CLOSE = _u(0x6628, 0x6536)
COL_CHANGE_PERCENT = _u(0x6DA8, 0x8DCC, 0x5E45)
COL_VOLUME = _u(0x6210, 0x4EA4, 0x91CF)
COL_VOLUME_RATIO = _u(0x91CF, 0x6BD4)
VOLUME_SIGNAL_UP = _u(0x653E, 0x91CF)
VOLUME_SIGNAL_DOWN = _u(0x7F29, 0x91CF)
VOLUME_SIGNAL_FLAT = _u(0x5E73, 0x91CF)
COL_NEWS_TITLE = _u(0x65B0, 0x95FB, 0x6807, 0x9898)
COL_TITLE = _u(0x6807, 0x9898)
COL_NEWS_SOURCE = _u(0x6587, 0x7AE0, 0x6765, 0x6E90)
COL_SOURCE = _u(0x6765, 0x6E90)
COL_NEWS_LINK = _u(0x65B0, 0x95FB, 0x94FE, 0x63A5)
COL_LINK = _u(0x94FE, 0x63A5)
COL_NEWS_CONTENT = _u(0x65B0, 0x95FB, 0x5185, 0x5BB9)
COL_SUMMARY = _u(0x6458, 0x8981)
COL_CONTENT = _u(0x5185, 0x5BB9)
COL_PUBLISHED_AT = _u(0x53D1, 0x5E03, 0x65F6, 0x95F4)
COL_DATE = _u(0x65E5, 0x671F)
COL_TIME = _u(0x65F6, 0x95F4)
COL_ANN_TITLE = _u(0x516C, 0x544A, 0x6807, 0x9898)
COL_ANN_TYPE = _u(0x516C, 0x544A, 0x7C7B, 0x578B)
COL_TYPE = _u(0x7C7B, 0x578B)
COL_ANN_URL = _u(0x7F51, 0x5740)
COL_ANN_DATE = _u(0x516C, 0x544A, 0x65E5, 0x671F)


class MarketDataProvider:
    def fetch_quote(self, market: str, symbol: str) -> NormalizedQuote | None:
        market = normalize_market(market)
        symbol = normalize_symbol(symbol, market)
        if market == "CN":
            quote = self._fetch_akshare_cn_quote(symbol)
            if quote:
                return quote
        return self._fetch_yfinance_quote(market, symbol)

    def _fetch_akshare_cn_quote(self, symbol: str) -> NormalizedQuote | None:
        try:
            import akshare as ak  # type: ignore
        except Exception:
            return None

        try:
            spot = ak.stock_zh_a_spot_em()
            quote = _quote_from_dataframe(spot, symbol, "AKShare A股")
            if quote:
                return quote
        except Exception:
            pass

        try:
            etf_spot = ak.fund_etf_spot_em()
            return _quote_from_dataframe(etf_spot, symbol, "AKShare ETF")
        except Exception:
            return None

    def fetch_trading_data(self, market: str, symbol: str) -> NormalizedTradingData | None:
        quote = self.fetch_quote(market, symbol)
        if quote is None:
            return None
        return NormalizedTradingData(
            symbol=quote.symbol,
            market=quote.market,
            price=quote.price,
            change_percent=quote.change_percent,
            volume=quote.volume,
            volume_ratio=quote.volume_ratio,
            volume_signal=quote.volume_signal,
            source=quote.source,
            raw_data=json.dumps(
                {
                    "price": quote.price,
                    "open": quote.open,
                    "high": quote.high,
                    "low": quote.low,
                    "previous_close": quote.previous_close,
                    "change_percent": quote.change_percent,
                    "volume": quote.volume,
                    "volume_ratio": quote.volume_ratio,
                    "volume_signal": quote.volume_signal,
                },
                ensure_ascii=False,
            ),
        )

    def fetch_historical_prices(self, market: str, symbol: str, period: str = "1mo") -> list[NormalizedHistoricalPrice]:
        market = normalize_market(market)
        symbol = normalize_symbol(symbol, market)
        if market == "CN":
            prices = self._fetch_akshare_cn_history(symbol, period)
            if prices:
                return prices
        return self._fetch_yfinance_history(market, symbol, period)

    def _fetch_yfinance_history(self, market: str, symbol: str, period: str) -> list[NormalizedHistoricalPrice]:
        try:
            import yfinance as yf  # type: ignore

            frame = yf.Ticker(to_yfinance_symbol(symbol, market)).history(period=period, interval="1d")
            if frame.empty:
                return []
            prices: list[NormalizedHistoricalPrice] = []
            for index, row in frame.iterrows():
                trade_date = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
                if trade_date.tzinfo is None:
                    trade_date = trade_date.replace(tzinfo=timezone.utc)
                prices.append(
                    NormalizedHistoricalPrice(
                        symbol=symbol,
                        market=market,
                        trade_date=trade_date,
                        open=_float_or_none(row.get("Open")),
                        high=_float_or_none(row.get("High")),
                        low=_float_or_none(row.get("Low")),
                        close=_float_or_none(row.get("Close")),
                        volume=_float_or_none(row.get("Volume")),
                        source="yfinance history",
                    )
                )
            return prices
        except Exception:
            return []

    def _fetch_akshare_cn_history(self, symbol: str, period: str) -> list[NormalizedHistoricalPrice]:
        try:
            import akshare as ak  # type: ignore
        except Exception:
            return []

        try:
            frame = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="")
        except Exception:
            try:
                frame = ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust="")
            except Exception:
                return []

        if frame.empty:
            return []
        cutoff_days = {"5d": 8, "1mo": 45, "3mo": 120, "6mo": 220, "1y": 420}.get(period, 45)
        frame = frame.tail(cutoff_days)
        prices: list[NormalizedHistoricalPrice] = []
        for _, row in frame.iterrows():
            date_value = _row_get(row, COL_DATE) or _row_get(row, _u(0x4EA4, 0x6613, 0x65E5))
            trade_date = _parse_datetime(date_value) or datetime.now(timezone.utc)
            prices.append(
                NormalizedHistoricalPrice(
                    symbol=symbol,
                    market="CN",
                    trade_date=trade_date,
                    open=_float_or_none(_row_get(row, COL_OPEN, COL_OPEN_ETF)),
                    high=_float_or_none(_row_get(row, COL_HIGH, COL_HIGH_ETF)),
                    low=_float_or_none(_row_get(row, COL_LOW, COL_LOW_ETF)),
                    close=_float_or_none(_row_get(row, COL_PRICE, _u(0x6536, 0x76D8))),
                    volume=_float_or_none(_row_get(row, COL_VOLUME)),
                    source="AKShare history",
                )
            )
        return prices

    def fetch_order_book(self, market: str, symbol: str) -> NormalizedOrderBook | None:
        market = normalize_market(market)
        symbol = normalize_symbol(symbol, market)
        if market != "CN":
            return None
        try:
            import akshare as ak  # type: ignore

            frame = ak.stock_bid_ask_em(symbol=symbol)
            raw = frame.to_dict(orient="records")
            return NormalizedOrderBook(
                symbol=symbol,
                market=market,
                source="东方财富盘口",
                levels=json.dumps(raw, ensure_ascii=False, default=str),
            )
        except Exception:
            return None

    def fetch_institutional_flow(self, market: str, symbol: str) -> NormalizedInstitutionalFlow | None:
        market = normalize_market(market)
        symbol = normalize_symbol(symbol, market)
        history = self.fetch_historical_prices(market, symbol, "1mo")
        cost = _institutional_cost_proxy(history)
        finra = self._fetch_finra_dark_pool_summary(symbol) if market == "US" else {}
        if not cost and not finra:
            return None
        raw = {
            "note": (
                "Cost values are volume-weighted proxy estimates from public OHLCV data. "
                "FINRA ATS/OTC data is delayed aggregate transparency data, not execution-level institution cost."
            ),
            "cost_proxy": cost,
            "finra": finra,
        }
        return NormalizedInstitutionalFlow(
            symbol=symbol,
            market=market,
            source="FINRA ATS/OTC + VWAP proxy" if finra else "VWAP proxy",
            vwap_proxy=cost.get("vwap_proxy"),
            cost_low=cost.get("cost_low"),
            cost_high=cost.get("cost_high"),
            dark_pool_volume=finra.get("ats_volume"),
            off_exchange_volume=finra.get("non_ats_volume"),
            sample_days=int(cost.get("sample_days") or 0),
            raw_data=json.dumps(raw, ensure_ascii=False, default=str),
        )

    def _fetch_finra_dark_pool_summary(self, symbol: str) -> dict[str, float | str]:
        payload = {
            "compareFilters": [{"compareType": "EQUAL", "fieldName": "issueSymbolIdentifier", "fieldValue": symbol}],
            "limit": 100,
            "sortFields": ["-weekStartDate"],
        }
        headers = {"User-Agent": "stock-info-service/0.1", "Accept": "application/json"}
        try:
            response = httpx.post(
                "https://api.finra.org/data/group/otcMarket/name/weeklySummary",
                json=payload,
                headers=headers,
                timeout=12.0,
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                return {}
            return _summarize_finra_rows(rows)
        except Exception:
            return {}

    def _fetch_yfinance_quote(self, market: str, symbol: str) -> NormalizedQuote | None:
        try:
            import yfinance as yf  # type: ignore

            ticker = yf.Ticker(to_yfinance_symbol(symbol, market))
            info = ticker.fast_info
            last_price = _float_or_none(getattr(info, "last_price", None))
            previous_close = _float_or_none(getattr(info, "previous_close", None))
            hist = None
            if last_price is None:
                hist = ticker.history(period="1mo")
                if hist.empty:
                    return None
                item = hist.iloc[-1]
                last_price = _float_or_none(item.get("Close"))
                previous_close = _float_or_none(item.get("Open"))
                volume = _float_or_none(item.get("Volume"))
            else:
                volume = _float_or_none(getattr(info, "last_volume", None))
            if hist is None:
                try:
                    hist = ticker.history(period="1mo")
                except Exception:
                    hist = None
            volume_ratio = _volume_ratio_from_history(hist, volume)
            change_percent = None
            if last_price is not None and previous_close:
                change_percent = (last_price - previous_close) / previous_close * 100
            return NormalizedQuote(
                symbol=symbol,
                market=market,
                price=last_price,
                previous_close=previous_close,
                change_percent=change_percent,
                volume=volume,
                volume_ratio=volume_ratio,
                volume_signal=classify_volume_signal(volume_ratio),
                source="yfinance",
            )
        except Exception:
            return None


class StockIdentityProvider:
    def __init__(self, remote_lookup: bool = True) -> None:
        self.remote_lookup = remote_lookup

    def resolve(self, market: str, symbol: str) -> ResolvedStock | None:
        market = normalize_market(market)
        symbol = normalize_symbol(symbol, market)
        candidate = self._local_candidate(market, symbol)
        if candidate is None:
            return None
        if not self.remote_lookup:
            return candidate
        if market == "CN":
            return self._resolve_akshare_cn(symbol) or self._resolve_akshare_cn_etf(symbol)
        return self._resolve_yfinance(market, symbol)

    @staticmethod
    def _local_candidate(market: str, symbol: str) -> ResolvedStock | None:
        if market == "CN":
            valid = symbol.isdigit() and len(symbol) == 6
        elif market == "HK":
            valid = symbol.isdigit() and 1 <= len(symbol) <= 5
        elif market == "US":
            valid = re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", symbol) is not None
        else:
            valid = False
        if not valid:
            return None
        return ResolvedStock(market=market, symbol=symbol, name=symbol, source="local validation")

    def _resolve_akshare_cn(self, symbol: str) -> ResolvedStock | None:
        try:
            import akshare as ak  # type: ignore

            spot = ak.stock_zh_a_spot_em()
            row = _find_symbol_row(spot, symbol)
            if row.empty:
                return None
            item = row.iloc[0]
            name = str(_row_get(item, COL_NAME) or "").strip()
            if not name:
                return None
            return ResolvedStock(market="CN", symbol=symbol, name=name, source="AKShare")
        except Exception:
            return None

    def _resolve_akshare_cn_etf(self, symbol: str) -> ResolvedStock | None:
        try:
            import akshare as ak  # type: ignore

            spot = ak.fund_etf_spot_em()
            row = _find_symbol_row(spot, symbol)
            if row.empty:
                return None
            item = row.iloc[0]
            name = str(_row_get(item, COL_NAME) or "").strip()
            if not name:
                return None
            return ResolvedStock(market="CN", symbol=symbol, name=name, source="AKShare ETF")
        except Exception:
            return None

    def _resolve_yfinance(self, market: str, symbol: str) -> ResolvedStock | None:
        try:
            import yfinance as yf  # type: ignore

            yf_symbol = to_yfinance_symbol(symbol, market)
            ticker = yf.Ticker(yf_symbol)
            try:
                info = ticker.get_info()
            except AttributeError:
                info = ticker.info
            name = (
                info.get("longName")
                or info.get("shortName")
                or info.get("displayName")
                or info.get("symbol")
                or ""
            )
            name = str(name).strip()
            if not name:
                return None
            return ResolvedStock(market=market, symbol=normalize_symbol(symbol, market), name=name, source="yfinance")
        except Exception:
            return None


class MarketIndexProvider:
    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def fetch_indices(self, full_history: bool = False) -> list[NormalizedMarketIndex]:
        points = self._fetch_cnn_fear_greed(full_history=full_history)
        for code, symbol in YFINANCE_INDEX_SYMBOLS.items():
            points.extend(self._fetch_yfinance_index(code, symbol, full_history=full_history))
        return points

    def _fetch_cnn_fear_greed(self, full_history: bool = False) -> list[NormalizedMarketIndex]:
        definition = _market_index_definition("fear_greed")
        points = self._fetch_cnn_fear_greed_archive(definition) if full_history else []
        try:
            response = httpx.get(
                CNN_FEAR_GREED_URL,
                headers=CNN_FEAR_GREED_HEADERS,
                timeout=self.timeout,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return points

        historical = payload.get("fear_and_greed_historical") or {}
        for item in historical.get("data") or []:
            value = _float_or_none(item.get("y")) if isinstance(item, dict) else None
            timestamp = _float_or_none(item.get("x")) if isinstance(item, dict) else None
            if value is None or timestamp is None or not math.isfinite(value):
                continue
            points.append(
                NormalizedMarketIndex(
                    code=definition.code,
                    name=definition.name,
                    value=value,
                    observed_at=datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc),
                    status=_fear_greed_status(str(item.get("rating") or ""), value),
                    source=definition.source,
                )
            )

        latest = payload.get("fear_and_greed") or {}
        latest_value = _float_or_none(latest.get("score")) if isinstance(latest, dict) else None
        latest_time = _parse_datetime(latest.get("timestamp")) if isinstance(latest, dict) else None
        if latest_value is not None and latest_time is not None and math.isfinite(latest_value):
            points.append(
                NormalizedMarketIndex(
                    code=definition.code,
                    name=definition.name,
                    value=latest_value,
                    observed_at=latest_time,
                    status=_fear_greed_status(str(latest.get("rating") or ""), latest_value),
                    source=definition.source,
                )
            )
        return points

    def _fetch_cnn_fear_greed_archive(
        self, definition: MarketIndexDefinition
    ) -> list[NormalizedMarketIndex]:
        try:
            response = httpx.get(
                CNN_FEAR_GREED_ARCHIVE_URL,
                headers={"User-Agent": "stock-info-service/0.1", "Accept": "text/csv"},
                timeout=self.timeout,
                follow_redirects=True,
            )
            response.raise_for_status()
            rows = csv.DictReader(response.text.splitlines())
            points = []
            for row in rows:
                value = _float_or_none(row.get("Fear Greed"))
                observed_at = _to_utc_datetime(row.get("Date"))
                if value is None or observed_at is None or not math.isfinite(value):
                    continue
                points.append(
                    NormalizedMarketIndex(
                        code=definition.code,
                        name=definition.name,
                        value=value,
                        observed_at=observed_at,
                        status=_fear_greed_status(str(row.get("Rating") or ""), value),
                        source="CNN / historical archive",
                    )
                )
            return points
        except Exception:
            return []

    def _fetch_yfinance_index(
        self, code: str, symbol: str, full_history: bool = False
    ) -> list[NormalizedMarketIndex]:
        definition = _market_index_definition(code)
        try:
            import yfinance as yf  # type: ignore

            ticker = yf.Ticker(symbol)
        except Exception:
            return []

        frames = []
        try:
            frames.append(
                ticker.history(period="max" if full_history else "1y", interval="1d", auto_adjust=False)
            )
        except Exception:
            pass
        try:
            # Yahoo occasionally omits the newest MOVE observations from long-range queries.
            frames.append(ticker.history(period="5d", interval="1d", auto_adjust=False))
        except Exception:
            pass

        by_time: dict[datetime, NormalizedMarketIndex] = {}
        for frame in frames:
            if frame is None or frame.empty:
                continue
            for index, row in frame.iterrows():
                value = _float_or_none(row.get("Close"))
                observed_at = _to_utc_datetime(index)
                if value is None or observed_at is None or not math.isfinite(value):
                    continue
                by_time[observed_at] = NormalizedMarketIndex(
                    code=definition.code,
                    name=definition.name,
                    value=value,
                    observed_at=observed_at,
                    unit=definition.unit,
                    source=definition.source,
                )
        return list(by_time.values())


class NewsProvider:
    def __init__(self, timeout: float = 12.0) -> None:
        self.timeout = timeout

    async def fetch_news(self) -> list[NormalizedArticle]:
        return await self._fetch_feeds(DEFAULT_NEWS_FEEDS)

    async def fetch_macro(self) -> list[NormalizedArticle]:
        return await self._fetch_feeds(DEFAULT_MACRO_FEEDS)

    async def fetch_stock_news(self, stock: Stock) -> list[NormalizedArticle]:
        articles: list[NormalizedArticle] = []
        if stock.market == "CN":
            articles.extend(self._fetch_akshare_stock_news(stock))
        articles.extend(self._fetch_yfinance_stock_news(stock))
        return articles

    async def fetch_announcements(self, stock: Stock) -> list[NormalizedArticle]:
        if stock.market == "CN":
            return self._fetch_akshare_announcements(stock)
        return self._fetch_yfinance_filings(stock)

    async def _fetch_feeds(self, feeds: Iterable[tuple[str, str]]) -> list[NormalizedArticle]:
        articles: list[NormalizedArticle] = []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for source, url in feeds:
                try:
                    response = await client.get(url, headers={"User-Agent": "stock-info-service/0.1"})
                    response.raise_for_status()
                    articles.extend(parse_rss(source, response.text))
                except Exception:
                    continue
        return articles

    def _fetch_akshare_stock_news(self, stock: Stock) -> list[NormalizedArticle]:
        try:
            import akshare as ak  # type: ignore

            frame = ak.stock_news_em(symbol=stock.symbol)
            articles: list[NormalizedArticle] = []
            for _, row in frame.head(30).iterrows():
                title = str(_row_get(row, COL_NEWS_TITLE, COL_TITLE, "title") or "").strip()
                if not title:
                    continue
                articles.append(
                    NormalizedArticle(
                        title=title,
                        source=str(_row_get(row, COL_NEWS_SOURCE, COL_SOURCE) or "东方财富个股新闻"),
                        url=str(_row_get(row, COL_NEWS_LINK, COL_LINK, "url") or ""),
                        summary=str(_row_get(row, COL_NEWS_CONTENT, COL_SUMMARY, COL_CONTENT) or ""),
                        published_at=_parse_datetime(_row_get(row, COL_PUBLISHED_AT, COL_DATE, COL_TIME)),
                        stock_symbol=stock.symbol,
                        stock_market=stock.market,
                    )
                )
            return articles
        except Exception:
            return []

    def _fetch_yfinance_stock_news(self, stock: Stock) -> list[NormalizedArticle]:
        try:
            import yfinance as yf  # type: ignore

            ticker = yf.Ticker(to_yfinance_symbol(stock.symbol, stock.market))
            raw_news = getattr(ticker, "news", []) or []
            articles: list[NormalizedArticle] = []
            for item in raw_news[:30]:
                content = item.get("content", item) if isinstance(item, dict) else {}
                title = str(content.get("title") or item.get("title") or "").strip()
                if not title:
                    continue
                provider = content.get("provider") or {}
                click = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
                url = click.get("url") if isinstance(click, dict) else ""
                articles.append(
                    NormalizedArticle(
                        title=title,
                        source=str(provider.get("displayName") or "Yahoo Finance"),
                        url=str(url or ""),
                        summary=str(content.get("summary") or content.get("description") or ""),
                        published_at=_parse_datetime(content.get("pubDate") or content.get("displayTime")),
                        stock_symbol=stock.symbol,
                        stock_market=stock.market,
                    )
                )
            return articles
        except Exception:
            return []

    def _fetch_akshare_announcements(self, stock: Stock) -> list[NormalizedArticle]:
        try:
            import akshare as ak  # type: ignore

            frame = ak.stock_individual_notice_report(security=stock.symbol)
            articles: list[NormalizedArticle] = []
            for _, row in frame.head(50).iterrows():
                title = str(_row_get(row, COL_ANN_TITLE, COL_TITLE) or "").strip()
                if not title:
                    continue
                articles.append(
                    NormalizedArticle(
                        title=title,
                        source="东方财富公告",
                        url=str(_row_get(row, COL_ANN_URL, COL_LINK) or ""),
                        summary=str(_row_get(row, COL_ANN_TYPE, COL_TYPE) or ""),
                        published_at=_parse_datetime(_row_get(row, COL_ANN_DATE, COL_DATE)),
                        stock_symbol=stock.symbol,
                        stock_market=stock.market,
                    )
                )
            return articles
        except Exception:
            return []

    def _fetch_yfinance_filings(self, stock: Stock) -> list[NormalizedArticle]:
        try:
            import yfinance as yf  # type: ignore

            ticker = yf.Ticker(to_yfinance_symbol(stock.symbol, stock.market))
            raw = getattr(ticker, "sec_filings", None) or getattr(ticker, "get_sec_filings", lambda: [])()
            if raw is None:
                return []
            records = raw if isinstance(raw, list) else raw.to_dict(orient="records")
            articles: list[NormalizedArticle] = []
            for item in records[:30]:
                title = str(item.get("formType") or item.get("type") or item.get("title") or "SEC Filing")
                url = str(item.get("edgarUrl") or item.get("url") or "")
                articles.append(
                    NormalizedArticle(
                        title=title,
                        source="SEC / Yahoo Finance",
                        url=url,
                        summary=str(item),
                        published_at=_parse_datetime(item.get("date") or item.get("filingDate")),
                        stock_symbol=stock.symbol,
                        stock_market=stock.market,
                    )
                )
            return articles
        except Exception:
            return []


def parse_rss(source: str, payload: str) -> list[NormalizedArticle]:
    root = ElementTree.fromstring(payload)
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    articles: list[NormalizedArticle] = []
    for item in items[:30]:
        title = _first_text(item, ["title", "{http://www.w3.org/2005/Atom}title"])
        link = _first_text(item, ["link", "guid"])
        atom_link = item.find("{http://www.w3.org/2005/Atom}link")
        if atom_link is not None and atom_link.attrib.get("href"):
            link = atom_link.attrib["href"]
        summary = _first_text(
            item,
            [
                "description",
                "summary",
                "{http://www.w3.org/2005/Atom}summary",
                "{http://purl.org/rss/1.0/modules/content/}encoded",
            ],
        )
        if title:
            articles.append(
                NormalizedArticle(
                    title=title.strip(),
                    source=source,
                    url=(link or "").strip(),
                    summary=(summary or "").strip(),
                    published_at=datetime.now(timezone.utc),
                )
            )
    return articles


def _first_text(item: ElementTree.Element, names: list[str]) -> str:
    for name in names:
        child = item.find(name)
        if child is not None and child.text:
            return child.text
    return ""


def _quote_from_dataframe(frame: object, symbol: str, source: str) -> NormalizedQuote | None:
    row = _find_symbol_row(frame, symbol)
    if row.empty:
        return None
    item = row.iloc[0]
    volume_ratio = _float_or_none(_row_get(item, COL_VOLUME_RATIO))
    return NormalizedQuote(
        symbol=symbol,
        market="CN",
        price=_float_or_none(_row_get(item, COL_PRICE)),
        open=_float_or_none(_row_get(item, COL_OPEN, COL_OPEN_ETF)),
        high=_float_or_none(_row_get(item, COL_HIGH, COL_HIGH_ETF)),
        low=_float_or_none(_row_get(item, COL_LOW, COL_LOW_ETF)),
        previous_close=_float_or_none(_row_get(item, COL_PREV_CLOSE)),
        change_percent=_float_or_none(_row_get(item, COL_CHANGE_PERCENT)),
        volume=_float_or_none(_row_get(item, COL_VOLUME)),
        volume_ratio=volume_ratio,
        volume_signal=classify_volume_signal(volume_ratio),
        source=source,
    )


def _institutional_cost_proxy(history: list[NormalizedHistoricalPrice]) -> dict[str, float | int]:
    weighted: list[tuple[float, float]] = []
    for item in history:
        price = item.close
        volume = item.volume
        if price is None or volume is None or volume <= 0:
            continue
        weighted.append((price, volume))
    if not weighted:
        return {}

    total_volume = sum(volume for _, volume in weighted)
    vwap = sum(price * volume for price, volume in weighted) / total_volume
    variance = sum(volume * ((price - vwap) ** 2) for price, volume in weighted) / total_volume
    weighted_std = variance ** 0.5
    return {
        "vwap_proxy": round(vwap, 4),
        "cost_low": round(max(0, vwap - weighted_std), 4),
        "cost_high": round(vwap + weighted_std, 4),
        "sample_days": len(weighted),
    }


def _summarize_finra_rows(rows: list[object]) -> dict[str, float | str]:
    ats_volume = 0.0
    non_ats_volume = 0.0
    latest_week = ""
    for item in rows:
        if not isinstance(item, dict):
            continue
        latest_week = latest_week or str(
            item.get("weekStartDate")
            or item.get("week_start_date")
            or item.get("summaryStartDate")
            or item.get("date")
            or ""
        )
        volume = _float_or_none(
            item.get("totalWeeklyShareQuantity")
            or item.get("weeklyShareQuantity")
            or item.get("shareQuantity")
            or item.get("volume")
        )
        if volume is None:
            continue
        venue_type = str(
            item.get("summaryType")
            or item.get("tradeReportType")
            or item.get("tierIdentifier")
            or item.get("marketParticipantName")
            or ""
        ).lower()
        if "non" in venue_type and "ats" in venue_type:
            non_ats_volume += volume
        else:
            ats_volume += volume
    result: dict[str, float | str] = {}
    if ats_volume:
        result["ats_volume"] = ats_volume
    if non_ats_volume:
        result["non_ats_volume"] = non_ats_volume
    if latest_week:
        result["latest_week"] = latest_week
    return result


def _find_symbol_row(frame: object, symbol: str):
    columns = list(getattr(frame, "columns", []))
    code_column = COL_CODE if COL_CODE in columns else columns[0]
    return frame[frame[code_column].astype(str) == symbol]


def _row_get(row: object, *keys: str) -> object:
    for key in keys:
        try:
            value = row.get(key)
        except AttributeError:
            value = None
        if value is not None:
            return value
    return None


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def _to_utc_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        to_pydatetime = getattr(value, "to_pydatetime", None)
        if not callable(to_pydatetime):
            result = _parse_datetime(value)
            if result is None:
                return None
        else:
            result = to_pydatetime()
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _market_index_definition(code: str) -> MarketIndexDefinition:
    for definition in MARKET_INDEX_DEFINITIONS:
        if definition.code == code:
            return definition
    raise KeyError(code)


def _fear_greed_status(rating: str, value: float) -> str:
    normalized = rating.strip().lower().replace("_", " ")
    labels = {
        "extreme fear": "极度恐惧",
        "fear": "恐惧",
        "neutral": "中性",
        "greed": "贪婪",
        "extreme greed": "极度贪婪",
    }
    if normalized in labels:
        return labels[normalized]
    if value <= 25:
        return "极度恐惧"
    if value <= 45:
        return "恐惧"
    if value <= 55:
        return "中性"
    if value <= 75:
        return "贪婪"
    return "极度贪婪"


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_volume_signal(volume_ratio: float | None) -> str:
    if volume_ratio is None:
        return ""
    if volume_ratio >= 1.5:
        return VOLUME_SIGNAL_UP
    if volume_ratio <= 0.8:
        return VOLUME_SIGNAL_DOWN
    return VOLUME_SIGNAL_FLAT


def _volume_ratio_from_history(frame: object, latest_volume: float | None) -> float | None:
    if latest_volume is None or frame is None or getattr(frame, "empty", True):
        return None
    try:
        volumes = [_float_or_none(value) for value in frame["Volume"].tolist()]
    except Exception:
        return None
    volumes = [value for value in volumes if value is not None and value > 0]
    if len(volumes) < 2:
        return None
    baseline = volumes[:-1][-20:] or volumes[-20:]
    average_volume = sum(baseline) / len(baseline)
    if average_volume <= 0:
        return None
    return round(latest_volume / average_volume, 4)
