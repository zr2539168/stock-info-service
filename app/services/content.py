from __future__ import annotations

import hashlib


def content_hash(*parts: str) -> str:
    payload = "\n".join(part or "" for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compact_text(value: str, limit: int = 800) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."

