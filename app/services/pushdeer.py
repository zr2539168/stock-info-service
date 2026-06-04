from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.schemas import RuntimeConfig


@dataclass
class PushResult:
    ok: bool
    message: str


class PushDeerClient:
    def __init__(self, config: RuntimeConfig, timeout: float = 15.0) -> None:
        self.config = config
        self.timeout = timeout

    async def push(self, title: str, text: str) -> PushResult:
        if not self.config.pushdeer_pushkey:
            return PushResult(False, "PushDeer PushKey 未配置")
        payload = {
            "pushkey": self.config.pushdeer_pushkey,
            "text": title,
            "desp": text,
            "type": "markdown",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.config.pushdeer_endpoint, data=payload)
                response.raise_for_status()
                return PushResult(True, "PushDeer 推送成功")
        except Exception as exc:
            return PushResult(False, f"PushDeer 推送失败：{exc}")

    async def test_push(self) -> PushResult:
        return await self.push("Stock Info Service 测试", "这是一条来自本地股票信息服务的测试推送。")

