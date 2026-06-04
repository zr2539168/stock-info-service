from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from xml.etree import ElementTree

import httpx

from app.schemas import NormalizedArticle, NormalizedQuote, ResolvedStock
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
            row = spot[spot["代码"] == symbol]
            if row.empty:
                return None
            item = row.iloc[0]
            name = str(item.get("名称") or "").strip()
            if not name:
                return None
            return ResolvedStock(market="CN", symbol=symbol, name=name, source="AKShare")
        except Exception:
            return None

    def _resolve_akshare_cn_etf(self, symbol: str) -> ResolvedStock | None:
        try:
            import akshare as ak  # type: ignore

            spot = ak.fund_etf_spot_em()
            row = spot[spot["代码"] == symbol]
            if row.empty:
                return None
            item = row.iloc[0]
            name = str(item.get("名称") or "").strip()
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
    row = frame[frame["代码"] == symbol]
    if row.empty:
        return None
    item = row.iloc[0]
    return NormalizedQuote(
        symbol=symbol,
        market="CN",
        price=_float_or_none(item.get("最新价")),
        open=_float_or_none(item.get("今开") or item.get("开盘价")),
        high=_float_or_none(item.get("最高") or item.get("最高价")),
        low=_float_or_none(item.get("最低") or item.get("最低价")),
        previous_close=_float_or_none(item.get("昨收")),
        change_percent=_float_or_none(item.get("涨跌幅")),
        volume=_float_or_none(item.get("成交量")),
        source=source,
    )


def _float_or_none(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
