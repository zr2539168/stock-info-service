from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.schemas import RuntimeConfig
from app.services.content import compact_text


SYSTEM_PROMPT = (
    "你是严谨的股票市场信息分析助手。只基于提供的本地资料回答，"
    "不编造数据，不给确定性投资建议。输出中文，结构清晰，包含来源。"
)


@dataclass
class AiResult:
    ok: bool
    content: str
    error: str = ""


class DeepSeekClient:
    def __init__(self, config: RuntimeConfig, timeout: float = 45.0) -> None:
        self.config = config
        self.timeout = timeout

    async def complete(self, user_prompt: str, context: str = "") -> AiResult:
        if not self.config.deepseek_api_key:
            return AiResult(False, fallback_summary(user_prompt, context), "DeepSeek API Key 未配置")

        payload = {
            "model": self.config.deepseek_model or "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"本地资料：\n{context}\n\n任务：\n{user_prompt}"},
            ],
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.config.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        base_url = self.config.deepseek_base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return AiResult(True, content)
        except Exception as exc:
            return AiResult(False, fallback_summary(user_prompt, context), str(exc))

    async def test_connection(self) -> AiResult:
        return await self.complete("用一句话回复：连接正常。", "")


def build_brief_prompt(scope: str) -> str:
    return (
        f"请生成{scope}市场简报，包含：1. 核心变化；2. 个股或宏观重点；"
        "3. 需要继续跟踪的风险；4. 来源列表。结尾注明：非投资建议。"
    )


def fallback_summary(user_prompt: str, context: str) -> str:
    cleaned = compact_text(context or "暂无可用本地资料。", 1200)
    return (
        "DeepSeek 暂不可用，以下为本地资料摘要：\n\n"
        f"{cleaned}\n\n"
        "风险提示：免费数据源可能延迟或缺失，请以交易所和公司公告为准。\n\n"
        "非投资建议。"
    )

