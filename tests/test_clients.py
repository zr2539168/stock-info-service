import respx
from httpx import Response

from app.schemas import RuntimeConfig
from app.services.ai import DeepSeekClient
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

