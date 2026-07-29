from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name, "true" if default else "false")
    return value.lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(item.strip() for item in env(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class EnvSettings:
    app_name: str = env("APP_NAME", "Stock Info Service")
    timezone: str = env("APP_TIMEZONE", "Asia/Taipei")
    database_url: str = env("DATABASE_URL", "sqlite:///./data/stock_info.db")
    app_mode: str = env("APP_MODE", "local").lower()
    wechat_app_id: str = env("WECHAT_APP_ID", "wx4efb62102392fcec")
    cloudbase_env_id: str = env("CLOUDBASE_ENV_ID", "")
    cloudbase_service_name: str = env("CLOUDBASE_SERVICE_NAME", "stock-api")
    admin_openids: tuple[str, ...] = env_list("ADMIN_OPENIDS")
    user_secret_master_key: str = env("USER_SECRET_MASTER_KEY", "")
    session_secret: str = env("SESSION_SECRET", "")
    internal_api_token: str = env("INTERNAL_API_TOKEN", "")
    alert_template_id: str = env("ALERT_TEMPLATE_ID", "")
    brief_template_id: str = env("BRIEF_TEMPLATE_ID", "")
    wechat_qr_function_url: str = env("WECHAT_QR_FUNCTION_URL", "")
    allowed_deepseek_models: tuple[str, ...] = env_list(
        "ALLOWED_DEEPSEEK_MODELS", "deepseek-v4-flash,deepseek-chat,deepseek-reasoner"
    )
    deepseek_api_key: str = env("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = env("DEEPSEEK_MODEL", "deepseek-v4-flash")
    collection_enabled: bool = env_bool("COLLECTION_ENABLED", True)
    collect_all_cron: str = env("COLLECT_ALL_CRON", "0 * * * *")
    market_open_briefs_enabled: bool = env_bool("MARKET_OPEN_BRIEFS_ENABLED", True)
    cn_open_brief_cron: str = env("CN_OPEN_BRIEF_CRON", "0 10 * * 1-5")
    us_open_brief_cron: str = env("US_OPEN_BRIEF_CRON", "0 10 * * 1-5")
    daily_noon_brief_enabled: bool = env_bool("DAILY_NOON_BRIEF_ENABLED", True)
    daily_noon_brief_cron: str = env("DAILY_NOON_BRIEF_CRON", "0 12 * * *")


settings = EnvSettings()


def validate_cloud_settings() -> None:
    if settings.app_mode not in {"api", "admin"}:
        return
    missing = []
    required_values = {
        "CLOUDBASE_ENV_ID": settings.cloudbase_env_id,
        "CLOUDBASE_SERVICE_NAME": settings.cloudbase_service_name,
        "ADMIN_OPENIDS": settings.admin_openids,
        "USER_SECRET_MASTER_KEY": settings.user_secret_master_key,
        "SESSION_SECRET": settings.session_secret,
        "INTERNAL_API_TOKEN": settings.internal_api_token,
    }
    for name, value in required_values.items():
        if not value:
            missing.append(name)
    if not settings.database_url.startswith(("mysql://", "mysql+pymysql://")):
        missing.append("DATABASE_URL(MySQL)")
    if missing:
        raise RuntimeError(f"云端环境变量未完整配置：{', '.join(missing)}")


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"
