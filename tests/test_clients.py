import respx
from httpx import Response

from app.schemas import RuntimeConfig
from app.services.ai import DeepSeekClient, estimate_tokens, needs_chinese_translation


def config(api_key: str = "test-key") -> RuntimeConfig:
    return RuntimeConfig(
        deepseek_api_key=api_key,
        deepseek_base_url="https://deepseek.test",
        deepseek_model="deepseek-v4-flash",
    )


async def _deepseek_call() -> str:
    result = await DeepSeekClient(config()).complete("测试", "上下文")
    return result.content


def test_deepseek_request_shape() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://deepseek.test/chat/completions").mock(
            return_value=Response(
                200, json={"choices": [{"message": {"content": "连接正常"}}]}
            )
        )
        import asyncio

        content = asyncio.run(_deepseek_call())

        assert content == "连接正常"
        payload = route.calls[0].request.content.decode()
        assert "deepseek-v4-flash" in payload
        assert "上下文" in payload


def test_deepseek_error_returns_explicit_local_fallback() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post("https://deepseek.test/chat/completions").mock(
            return_value=Response(401, json={"error": {"message": "invalid key"}})
        )
        import asyncio

        result = asyncio.run(DeepSeekClient(config()).complete("测试", "本地上下文"))

    assert not result.ok
    assert "DeepSeek 暂不可用" in result.content
    assert "本地上下文" in result.content
    assert "401" in result.error


async def _translation_call() -> tuple[str, str]:
    result = await DeepSeekClient(config()).translate_article_to_chinese(
        "Apple rises after earnings beat expectations",
        "Shares climbed after stronger iPhone revenue.",
    )
    return result.title, result.summary


async def _batch_translation_call() -> list[tuple[str, str]]:
    results = await DeepSeekClient(config()).translate_articles_to_chinese(
        [
            {
                "title": "Apple rises after earnings beat expectations",
                "summary": "Shares climbed.",
            },
            {
                "title": "Nvidia falls as traders take profit",
                "summary": "Chip stocks were mixed.",
            },
        ]
    )
    return [(item.title, item.summary) for item in results]


async def _chat_title_call() -> str:
    result = await DeepSeekClient(config()).summarize_chat_title(
        "请分析GOOGL", "GOOGL成交量放大。"
    )
    return result.content


def test_deepseek_translation_request_shape() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://deepseek.test/chat/completions").mock(
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
        import asyncio

        title, summary = asyncio.run(_translation_call())

        assert title == "苹果财报超预期后上涨"
        assert summary == "iPhone 收入强劲推动股价走高。"
        payload = route.calls[0].request.content.decode()
        assert "Apple rises" in payload
        assert "简体中文" in payload


def test_deepseek_batch_translation_request_shape() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://deepseek.test/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"items":['
                                    '{"title":"苹果财报超预期后上涨","summary":"股价上涨。"},'
                                    '{"title":"英伟达获利回吐下跌","summary":"芯片股涨跌互现。"}'
                                    "]}"
                                )
                            }
                        }
                    ]
                },
            )
        )
        import asyncio

        translated = asyncio.run(_batch_translation_call())

        assert translated == [
            ("苹果财报超预期后上涨", "股价上涨。"),
            ("英伟达获利回吐下跌", "芯片股涨跌互现。"),
        ]
        payload = route.calls[0].request.content.decode()
        assert "Apple rises" in payload
        assert "Nvidia falls" in payload
        assert len(route.calls) == 1


def test_deepseek_chat_title_request_shape() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://deepseek.test/chat/completions").mock(
            return_value=Response(
                200, json={"choices": [{"message": {"content": "GOOGL成交量分析"}}]}
            )
        )
        import asyncio

        title = asyncio.run(_chat_title_call())

        assert title == "GOOGL成交量分析"
        payload = route.calls[0].request.content.decode()
        assert "简短标题" in payload
        assert "GOOGL成交量放大" in payload


def test_translation_detection() -> None:
    assert needs_chinese_translation("Apple rises after earnings beat expectations", "")
    assert not needs_chinese_translation("苹果财报超预期后上涨", "")


def test_estimate_tokens_is_stable_for_ascii_and_cjk_text() -> None:
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("测试文本") >= 2


def test_runtime_config_contains_only_deepseek_connection_fields() -> None:
    assert set(RuntimeConfig.__dataclass_fields__) == {
        "deepseek_api_key",
        "deepseek_base_url",
        "deepseek_model",
    }
