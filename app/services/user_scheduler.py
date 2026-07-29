from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.database import engine
from app.models import FetchJobRun, User, UserPreference
from app.services.collector import finish_job, generate_daily_brief, start_job
from app.services.job_lock import acquire_job_lease, release_job_lease
from app.services.market_calendar import is_market_trading_day
from app.services.users import has_deepseek_key


def run_due_user_briefs_job() -> None:
    with Session(engine) as session:
        asyncio.run(run_due_user_briefs(session))


async def run_due_user_briefs(session: Session, now: datetime | None = None) -> int:
    now_utc = _as_utc(now or datetime.now(timezone.utc))
    users = session.exec(select(User).where(User.status == "active")).all()
    generated = 0
    for user in users:
        if user.id is None:
            continue
        preference = session.get(UserPreference, user.id)
        if preference is None:
            continue
        schedules: list[tuple[str, str, set[str] | None, str, str | None]] = []
        if preference.daily_brief_enabled:
            schedules.append(("daily", preference.daily_brief_time, None, "最新24小时", None))
        if preference.market_open_briefs_enabled:
            schedules.extend(
                [
                    ("cn_open", preference.cn_open_brief_time, {"CN", "HK"}, "A股/港股盘中", "CN"),
                    ("us_open", preference.us_open_brief_time, {"US"}, "美股盘中", "US"),
                ]
            )
        for schedule_type, due_time, markets, label, market in schedules:
            due, local_date = _is_due(now_utc, due_time, market)
            if not due:
                continue
            idempotency_key = f"user-brief:{user.id}:{schedule_type}:{local_date}"
            existing = session.exec(
                select(FetchJobRun).where(
                    FetchJobRun.idempotency_key == idempotency_key,
                    FetchJobRun.status.in_(("running", "success", "skipped")),
                )
            ).first()
            if existing is not None:
                continue
            owner = acquire_job_lease(session, idempotency_key, ttl_seconds=900)
            if owner is None:
                continue
            run = start_job(session, f"user_{schedule_type}_brief", user_id=user.id, idempotency_key=idempotency_key)
            try:
                if not has_deepseek_key(session, user.id):
                    finish_job(session, run, "skipped", "DeepSeek API Key 未配置")
                    continue
                await generate_daily_brief(
                    session,
                    push=True,
                    scope_label=label,
                    markets=markets,
                    latest_hours=24 if schedule_type == "daily" else None,
                    user_id=user.id,
                )
                finish_job(session, run, "success")
                generated += 1
            except Exception as exc:
                finish_job(session, run, "failed", str(exc))
            finally:
                release_job_lease(session, idempotency_key, owner)
    return generated


def _is_due(now_utc: datetime, time_text: str, market: str | None) -> tuple[bool, str]:
    timezone_name = "America/New_York" if market == "US" else "Asia/Shanghai"
    local = now_utc.astimezone(ZoneInfo(timezone_name))
    if market and not is_market_trading_day(market, local):
        return False, local.date().isoformat()
    try:
        hour, minute = (int(part) for part in time_text.split(":", 1))
    except (TypeError, ValueError):
        return False, local.date().isoformat()
    due = (local.hour, local.minute) >= (hour, minute)
    return due, local.date().isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
