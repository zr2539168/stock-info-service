from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable
from xml.etree import ElementTree

import httpx

from app.models import Stock
from app.schemas import NormalizedArticle, NormalizedOrderBook, NormalizedQuote, NormalizedTradingData, ResolvedStock
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
                },
                ensure_ascii=False,
            ),
        )

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

    def _fetch_yfinance_quote(self, market: str, symbol: str) -> NormalizedQuote | None:
        try:
            import yfinance as yf  # type: ignore

            ticker = yf.Ticker(to_yfinance_symbol(symbol, market))
            info = ticker.fast_info
            last_price = _float_or_none(getattr(info, "last_price", None))
            previous_close = _float_or_none(getattr(info, "previous_close", None))
            if last_price is None:
                hist = ticker.history(period="1d")
                if hist.empty:
                    return None
                item = hist.iloc[-1]
                last_price = _float_or_none(item.get("Close"))
                previous_close = _float_or_none(item.get("Open"))
                volume = _float_or_none(item.get("Volume"))
            else:
                volume = _float_or_none(getattr(info, "last_volume", None))
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
                source="yfinance",
            )
        except Exception:
            return None


class StockIdentityProvider:
    def resolve(self, market: str, symbol: str) -> ResolvedStock | None:
        market = normalize_market(market)
        symbol = normalize_symbol(symbol, market)
        if not symbol:
            return None
        if market == "CN":
            if not symbol.isdigit() or len(symbol) != 6:
                return None
            return self._resolve_akshare_cn(symbol) or self._resolve_akshare_cn_etf(symbol)
        if market == "HK" and not symbol.isdigit():
            return None
        return self._resolve_yfinance(market, symbol)

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
        source=source,
    )


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


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
