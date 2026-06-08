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
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class TranslationResult:
    ok: bool
    title: str
    summary: str
    error: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


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
                return _ai_result(True, content, "", data, payload)
        except Exception as exc:
            content = fallback_summary(user_prompt, context)
            return _ai_result(False, content, str(exc), {}, payload)

    async def complete_json(self, system_prompt: str, user_prompt: str) -> AiResult:
        if not self.config.deepseek_api_key:
            return AiResult(False, "", "DeepSeek API Key is not configured")

        payload = {
            "model": self.config.deepseek_model or "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
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
                return _ai_result(True, content, "", data, payload)
        except Exception as exc:
            return AiResult(False, "", str(exc))

    async def test_connection(self) -> AiResult:
        return await self.complete("用一句话回复：连接正常。", "")

    async def summarize_chat_title(self, question: str, answer: str) -> AiResult:
        if not self.config.deepseek_api_key:
            return AiResult(False, fallback_chat_title(question), "DeepSeek API Key 未配置")

        payload = {
            "model": self.config.deepseek_model or "deepseek-v4-flash",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是对话标题生成助手。根据用户问题和AI回答生成一个中文简短标题，"
                        "不超过18个汉字或30个字符，不要引号，不要标点堆砌，不要解释。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"用户问题：{question}\nAI回答：{compact_text(answer, 600)}\n请输出简短标题。",
                },
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
                content = cleanup_chat_title(data["choices"][0]["message"]["content"])
                return _ai_result(True, content or fallback_chat_title(question), "", data, payload)
        except Exception as exc:
            return _ai_result(False, fallback_chat_title(question), str(exc), {}, payload)

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
                usage = _usage_from_response(data, payload, content)
                return TranslationResult(
                    True,
                    translated.get("title") or title,
                    translated.get("summary") or summary,
                    prompt_tokens=usage[0],
                    completion_tokens=usage[1],
                    total_tokens=usage[2],
                )
        except Exception as exc:
            return TranslationResult(False, title, summary, str(exc))

    async def translate_articles_to_chinese(self, articles: list[dict[str, str]]) -> list[TranslationResult]:
        if not articles:
            return []
        if not self.config.deepseek_api_key:
            return [
                TranslationResult(False, item.get("title", ""), item.get("summary", ""), "DeepSeek API Key 未配置")
                for item in articles
            ]

        payload_items = [
            {"index": index, "title": item.get("title", ""), "summary": item.get("summary", "")}
            for index, item in enumerate(articles)
        ]
        payload = {
            "model": self.config.deepseek_model or "deepseek-v4-flash",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是财经新闻翻译助手。把输入数组中的标题和摘要翻译成简体中文，"
                        "保持股票代码、公司名、数字、日期、来源名和专有名词准确。"
                        "只返回 JSON，不要 Markdown，不要解释。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "请翻译以下 JSON 数组，返回格式必须是："
                        '{"items":[{"index":0,"title":"中文标题","summary":"中文摘要"}]}\n'
                        f"{json.dumps({'items': payload_items}, ensure_ascii=False)}"
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
                usage = _usage_from_response(data, payload, content)
                translated = _parse_batch_translation_json(content)
                by_index = {item["index"]: item for item in translated}
                results: list[TranslationResult] = []
                for index, source in enumerate(articles):
                    item = by_index.get(index, {})
                    results.append(
                        TranslationResult(
                            True,
                            item.get("title") or source.get("title", ""),
                            item.get("summary") or source.get("summary", ""),
                            prompt_tokens=usage[0] if index == 0 else 0,
                            completion_tokens=usage[1] if index == 0 else 0,
                            total_tokens=usage[2] if index == 0 else 0,
                        )
                    )
                return results
        except Exception as exc:
            return [
                TranslationResult(False, item.get("title", ""), item.get("summary", ""), str(exc))
                for item in articles
            ]


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


def fallback_chat_title(question: str) -> str:
    title = cleanup_chat_title(question)
    return title or "新的对话"


def cleanup_chat_title(title: str) -> str:
    cleaned = " ".join((title or "").strip().strip("\"'“”‘’`").split())
    for prefix in ("标题：", "简短标题：", "对话标题："):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    return compact_text(cleaned, 30)


def needs_chinese_translation(title: str, summary: str = "") -> bool:
    text = f"{title or ''} {summary or ''}".strip()
    if not text:
        return False
    latin = sum(1 for char in text if ("A" <= char <= "Z") or ("a" <= char <= "z"))
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return latin >= 12 and cjk * 2 < latin


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    other_chars = len(text) - ascii_chars
    return max(1, round(ascii_chars / 4 + other_chars / 1.8))


def _ai_result(ok: bool, content: str, error: str, data: dict, payload: dict) -> AiResult:
    prompt_tokens, completion_tokens, total_tokens = _usage_from_response(data, payload, content)
    return AiResult(ok, content, error, prompt_tokens, completion_tokens, total_tokens)


def _usage_from_response(data: dict, payload: dict, content: str) -> tuple[int, int, int]:
    usage = data.get("usage") if isinstance(data, dict) else None
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or prompt + completion)
        return prompt, completion, total
    prompt_text = json.dumps(payload.get("messages", []), ensure_ascii=False)
    prompt = estimate_tokens(prompt_text)
    completion = estimate_tokens(content)
    return prompt, completion, prompt + completion


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


def _parse_batch_translation_json(content: str) -> list[dict[str, str | int]]:
    text = (content or "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        raise ValueError("Batch translation response does not include items")
    result: list[dict[str, str | int]] = []
    for fallback_index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "index": int(item.get("index") if item.get("index") is not None else fallback_index),
                "title": str(item.get("title") or ""),
                "summary": str(item.get("summary") or ""),
            }
        )
    return result
