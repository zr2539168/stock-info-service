from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session

from app.config import settings
from app.models import AppSetting
from app.schemas import RuntimeConfig


MARKET_OPEN_BRIEFS_ENABLED_KEY = "market_open_briefs_enabled"
CN_OPEN_BRIEF_CRON_KEY = "cn_open_brief_cron"
US_OPEN_BRIEF_CRON_KEY = "us_open_brief_cron"
COLLECTION_ENABLED_KEY = "collection_enabled"
COLLECT_ALL_CRON_KEY = "collect_all_cron"

SETTING_KEYS = {
    "deepseek_api_key": True,
    "deepseek_base_url": False,
    "deepseek_model": False,
    "pushdeer_pushkey": True,
    "pushdeer_endpoint": False,
    COLLECTION_ENABLED_KEY: False,
    COLLECT_ALL_CRON_KEY: False,
    MARKET_OPEN_BRIEFS_ENABLED_KEY: False,
    CN_OPEN_BRIEF_CRON_KEY: False,
    US_OPEN_BRIEF_CRON_KEY: False,
}


def get_setting(session: Session, key: str, default: str = "") -> str:
    item = session.get(AppSetting, key)
    return item.value if item else default


def set_setting(session: Session, key: str, value: str, secret: bool | None = None) -> None:
    if key not in SETTING_KEYS:
        raise ValueError(f"Unsupported setting: {key}")
    item = session.get(AppSetting, key)
    if item is None:
        item = AppSetting(key=key, value=value, secret=SETTING_KEYS[key] if secret is None else secret)
    else:
        item.value = value
        item.secret = SETTING_KEYS[key] if secret is None else secret
        item.updated_at = datetime.now(timezone.utc)
    session.add(item)
    session.commit()


def get_runtime_config(session: Session) -> RuntimeConfig:
    return RuntimeConfig(
        deepseek_api_key=get_setting(session, "deepseek_api_key", settings.deepseek_api_key),
        deepseek_base_url=get_setting(session, "deepseek_base_url", settings.deepseek_base_url),
        deepseek_model=get_setting(session, "deepseek_model", settings.deepseek_model),
        pushdeer_pushkey=get_setting(session, "pushdeer_pushkey", settings.pushdeer_pushkey),
        pushdeer_endpoint=get_setting(session, "pushdeer_endpoint", settings.pushdeer_endpoint),
    )


def get_market_open_brief_settings(session: Session) -> tuple[bool, str, str]:
    enabled = get_setting(session, MARKET_OPEN_BRIEFS_ENABLED_KEY, str(settings.market_open_briefs_enabled))
    return (
        enabled.lower() in {"1", "true", "yes", "on"},
        get_setting(session, CN_OPEN_BRIEF_CRON_KEY, settings.cn_open_brief_cron),
        get_setting(session, US_OPEN_BRIEF_CRON_KEY, settings.us_open_brief_cron),
    )


def get_collection_settings(session: Session) -> tuple[bool, str]:
    enabled = get_setting(session, COLLECTION_ENABLED_KEY, str(settings.collection_enabled))
    return (
        enabled.lower() in {"1", "true", "yes", "on"},
        get_setting(session, COLLECT_ALL_CRON_KEY, settings.collect_all_cron),
    )


def workday_time_to_cron(value: str) -> str:
    stripped = value.strip()
    try:
        hour_text, minute_text = stripped.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("简报时间必须使用 HH:MM 格式") from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("简报时间必须在 00:00 到 23:59 之间")
    return f"{minute} {hour} * * 1-5"


def cron_to_workday_time(value: str) -> str:
    parts = value.split()
    if len(parts) != 5:
        return ""
    minute, hour, day, month, weekday = parts
    if day != "*" or month != "*" or weekday != "1-5":
        return ""
    try:
        hour_num = int(hour)
        minute_num = int(minute)
    except ValueError:
        return ""
    if not (0 <= hour_num <= 23 and 0 <= minute_num <= 59):
        return ""
    return f"{hour_num:02d}:{minute_num:02d}"


def all_settings(session: Session) -> dict[str, str]:
    cfg = get_runtime_config(session)
    collection_enabled, collect_all_cron = get_collection_settings(session)
    market_open_enabled, cn_open_brief_cron, us_open_brief_cron = get_market_open_brief_settings(session)
    return {
        "deepseek_api_key": cfg.deepseek_api_key,
        "deepseek_base_url": cfg.deepseek_base_url,
        "deepseek_model": cfg.deepseek_model,
        "pushdeer_pushkey": cfg.pushdeer_pushkey,
        "pushdeer_endpoint": cfg.pushdeer_endpoint,
        "collection_enabled": "true" if collection_enabled else "false",
        "collect_all_cron": collect_all_cron,
        "market_open_briefs_enabled": "true" if market_open_enabled else "false",
        "cn_open_brief_cron": cn_open_brief_cron,
        "cn_open_brief_time": cron_to_workday_time(cn_open_brief_cron),
        "us_open_brief_cron": us_open_brief_cron,
        "us_open_brief_time": cron_to_workday_time(us_open_brief_cron),
    }

