import asyncio

import respx
from httpx import Response
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import AppSetting, NewsItem, Stock
from app.schemas import NormalizedArticle
from app.services.collector import collect_news


class FakeNewsProvider:
    async def fetch_stock_news(self, stock: Stock) -> list[NormalizedArticle]:
        return [
            NormalizedArticle(
                title="Apple rises after earnings beat expectations",
                source="Yahoo Finance",
                summary="Shares climbed after stronger iPhone revenue.",
                url="https://example.com/aapl",
            )
        ]


def test_collect_news_translates_english_articles_before_saving() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(Stock(market="US", symbol="AAPL", name="Apple Inc."))
        session.add(AppSetting(key="deepseek_api_key", value="test-key", secret=True))
        session.add(AppSetting(key="deepseek_base_url", value="https://deepseek.test"))
        session.add(AppSetting(key="deepseek_model", value="deepseek-v4-flash"))
        session.commit()

        with respx.mock(assert_all_called=True) as router:
            router.post("https://deepseek.test/chat/completions").mock(
                return_value=Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": '{"title":"苹果财报超预期后上涨","summary":"iPhone 收入强劲推动股价走高。"}'
                                }
                            }
                        ]
                    },
                )
            )
            count = asyncio.run(collect_news(session, FakeNewsProvider()))

        item = session.exec(select(NewsItem)).first()

        assert count == 1
        assert item is not None
        assert item.title == "苹果财报超预期后上涨"
        assert item.summary == "iPhone 收入强劲推动股价走高。"
