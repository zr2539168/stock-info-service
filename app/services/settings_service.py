from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session

from app.config import settings
from app.models import AppSetting
from app.schemas import RuntimeConfig


SETTING_KEYS = {
    "deepseek_api_key": True,
    "deepseek_base_url": False,
    "deepseek_model": False,
    "pushdeer_pushkey": True,
    "pushdeer_endpoint": False,
    "brief_schedule_cron": False,
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


def all_settings(session: Session) -> dict[str, str]:
    cfg = get_runtime_config(session)
    return {
        "deepseek_api_key": cfg.deepseek_api_key,
        "deepseek_base_url": cfg.deepseek_base_url,
        "deepseek_model": cfg.deepseek_model,
        "pushdeer_pushkey": cfg.pushdeer_pushkey,
        "pushdeer_endpoint": cfg.pushdeer_endpoint,
    }

