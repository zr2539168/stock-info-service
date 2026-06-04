import respx
from httpx import Response

from app.schemas import RuntimeConfig
from app.services.ai import DeepSeekClient, needs_chinese_translation
from app.services.pushdeer import PushDeerClient


def config(api_key: str = "test-key", pushkey: str = "push-key") -> RuntimeConfig:
    return RuntimeConfig(
        deepseek_api_key=api_key,
        deepseek_base_url="https://deepseek.test",
        deepseek_model="deepseek-v4-flash",
        pushdeer_pushkey=pushkey,
        pushdeer_endpoint="https://pushdeer.test/message/push",
    )


async def _deepseek_call() -> str:
    result = await DeepSeekClient(config()).complete("测试", "上下文")
    return result.content


def test_deepseek_request_shape() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://deepseek.test/chat/completions").mock(
            return_value=Response(200, json={"choices": [{"message": {"content": "连接正常"}}]})
        )
        import asyncio

        content = asyncio.run(_deepseek_call())

        assert content == "连接正常"
        payload = route.calls[0].request.content.decode()
        assert "deepseek-v4-flash" in payload
        assert "上下文" in payload


async def _translation_call() -> tuple[str, str]:
    result = await DeepSeekClient(config()).translate_article_to_chinese(
        "Apple rises after earnings beat expectations",
        "Shares climbed after stronger iPhone revenue.",
    )
    return result.title, result.summary


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


def test_translation_detection() -> None:
    assert needs_chinese_translation("Apple rises after earnings beat expectations", "")
    assert not needs_chinese_translation("苹果财报超预期后上涨", "")


async def _push_call() -> str:
    result = await PushDeerClient(config()).push("标题", "正文")
    return result.message


def test_pushdeer_request_shape() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://pushdeer.test/message/push").mock(return_value=Response(200, json={"code": 0}))
        import asyncio

        message = asyncio.run(_push_call())

        assert message == "PushDeer 推送成功"
        body = route.calls[0].request.content.decode()
        assert "push-key" in body
        assert "title" not in body


def test_pushdeer_nonzero_code_is_failure() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post("https://pushdeer.test/message/push").mock(
            return_value=Response(200, json={"code": 80501, "error": "The pushkey field is required."})
        )
        import asyncio

        message = asyncio.run(_push_call())

        assert "PushDeer 推送失败" in message
        assert "80501" in message
