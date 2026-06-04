from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class EnvSettings:
    app_name: str = env("APP_NAME", "Stock Info Service")
    timezone: str = env("APP_TIMEZONE", "Asia/Taipei")
    database_url: str = env("DATABASE_URL", "sqlite:///./data/stock_info.db")
    deepseek_api_key: str = env("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = env("DEEPSEEK_MODEL", "deepseek-v4-flash")
    pushdeer_pushkey: str = env("PUSHDEER_PUSHKEY", "")
    pushdeer_endpoint: str = env(
        "PUSHDEER_ENDPOINT", "https://api2.pushdeer.com/message/push"
    )
    fetch_quotes_cron: str = env("FETCH_QUOTES_CRON", "*/5 * * * *")
    fetch_news_cron: str = env("FETCH_NEWS_CRON", "*/30 * * * *")
    fetch_macro_cron: str = env("FETCH_MACRO_CRON", "15 7 * * *")
    daily_brief_cron: str = env("DAILY_BRIEF_CRON", "5 16 * * 1-5")


settings = EnvSettings()


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"

