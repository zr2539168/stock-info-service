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
    collection_enabled: bool = env("COLLECTION_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    collect_all_cron: str = env("COLLECT_ALL_CRON", "0 * * * *")
    market_open_briefs_enabled: bool = env("MARKET_OPEN_BRIEFS_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    cn_open_brief_cron: str = env("CN_OPEN_BRIEF_CRON", "0 10 * * 1-5")
    us_open_brief_cron: str = env("US_OPEN_BRIEF_CRON", "0 10 * * 1-5")
    daily_noon_brief_enabled: bool = env("DAILY_NOON_BRIEF_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    daily_noon_brief_cron: str = env("DAILY_NOON_BRIEF_CRON", "0 12 * * *")


settings = EnvSettings()


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"
