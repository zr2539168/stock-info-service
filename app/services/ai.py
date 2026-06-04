from __future__ import annotations

import json
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


@dataclass
class TranslationResult:
    ok: bool
    title: str
    summary: str
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

    async def translate_article_to_chinese(self, title: str, summary: str = "") -> TranslationResult:
        if not self.config.deepseek_api_key:
            return TranslationResult(False, title, summary, "DeepSeek API Key 未配置")

        source_payload = {"title": title or "", "summary": summary or ""}
        payload = {
            "model": self.config.deepseek_model or "deepseek-v4-flash",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是财经新闻翻译助手。把输入的标题和摘要翻译成简体中文，"
                        "保持股票代码、公司名、数字、日期、来源名和专有名词准确。"
                        "只返回 JSON，不要 Markdown，不要解释。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "请翻译以下 JSON，返回格式必须是："
                        '{"title":"中文标题","summary":"中文摘要"}\n'
                        f"{json.dumps(source_payload, ensure_ascii=False)}"
                    ),
                },
            ],
            "temperature": 0.1,
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
                translated = _parse_translation_json(content)
                return TranslationResult(
                    True,
                    translated.get("title") or title,
                    translated.get("summary") or summary,
                )
        except Exception as exc:
            return TranslationResult(False, title, summary, str(exc))


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


def needs_chinese_translation(title: str, summary: str = "") -> bool:
    text = f"{title or ''} {summary or ''}".strip()
    if not text:
        return False
    latin = sum(1 for char in text if ("A" <= char <= "Z") or ("a" <= char <= "z"))
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return latin >= 12 and cjk * 2 < latin


def _parse_translation_json(content: str) -> dict[str, str]:
    text = (content or "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Translation response is not an object")
    return {
        "title": str(parsed.get("title") or ""),
        "summary": str(parsed.get("summary") or ""),
    }
