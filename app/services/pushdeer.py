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
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.post(self.config.pushdeer_endpoint, data=payload)
                response.raise_for_status()
                data = _json_or_empty(response)
                code = data.get("code")
                if code not in (None, 0):
                    error = data.get("error") or data.get("message") or response.text
                    return PushResult(False, f"PushDeer 推送失败：code={code} {error}")
                return PushResult(True, "PushDeer 推送成功")
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:300] if exc.response is not None else ""
            return PushResult(False, f"PushDeer 推送失败：HTTP {exc.response.status_code} {body}")
        except httpx.RequestError as exc:
            detail = str(exc) or repr(exc.__cause__) or repr(exc)
            return PushResult(False, f"PushDeer 推送失败：{type(exc).__name__} {detail}")
        except Exception as exc:
            detail = str(exc) or repr(exc)
            return PushResult(False, f"PushDeer 推送失败：{type(exc).__name__} {detail}")

    async def test_push(self) -> PushResult:
        return await self.push("Stock Info Service 测试", "这是一条来自本地股票信息服务的测试推送。")


def _json_or_empty(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}

