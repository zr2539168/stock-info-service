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
            ),
            NormalizedArticle(
                title="Nvidia falls as traders take profit",
                source="Yahoo Finance",
                summary="Chip stocks were mixed.",
                url="https://example.com/nvda",
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
                                    "content": (
                                        '{"items":['
                                        '{"title":"苹果财报超预期后上涨","summary":"iPhone 收入强劲推动股价走高。"},'
                                        '{"title":"英伟达获利回吐下跌","summary":"芯片股涨跌互现。"}'
                                        "]}"
                                    )
                                }
                            }
                        ]
                    },
                )
            )
            count = asyncio.run(collect_news(session, FakeNewsProvider()))

            assert len(router.calls) == 1

        items = session.exec(select(NewsItem).order_by(NewsItem.url)).all()

        assert count == 2
        assert [item.title for item in items] == ["苹果财报超预期后上涨", "英伟达获利回吐下跌"]
        assert [item.summary for item in items] == ["iPhone 收入强劲推动股价走高。", "芯片股涨跌互现。"]
