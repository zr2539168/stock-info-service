from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from app.config import settings
from app.database import engine
from app.models import FetchJobRun
from app.services.job_lock import acquire_collection_job_lock, release_collection_job_lock
from app.services.market_calendar import is_market_trading_day
from app.services.settings_service import (
    cron_to_workday_time,
    get_collection_settings,
    get_daily_noon_brief_settings,
    get_market_open_brief_settings,
)
from app.services.collector import (
    collect_all_information,
    finish_job,
    generate_daily_brief,
    push_pending_alert_events,
    start_job,
)


BRIEF_COLLECTION_WAIT_SECONDS = 60 * 60


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    configure_collection_job(scheduler, settings.collection_enabled, settings.collect_all_cron)
    configure_market_open_brief_jobs(
        scheduler,
        settings.market_open_briefs_enabled,
        settings.cn_open_brief_cron,
        settings.us_open_brief_cron,
    )
    configure_daily_noon_brief_job(
        scheduler,
        settings.daily_noon_brief_enabled,
        settings.daily_noon_brief_cron,
    )
    return scheduler


def configure_collection_job(scheduler: BackgroundScheduler, enabled: bool, cron: str) -> None:
    if scheduler.get_job("collect_all") is not None:
        scheduler.remove_job("collect_all")
    if not enabled:
        return
    scheduler.add_job(
        _run_collect_all_job,
        CronTrigger.from_crontab(cron),
        id="collect_all",
        replace_existing=True,
    )


def configure_market_open_brief_jobs(
    scheduler: BackgroundScheduler,
    enabled: bool,
    cn_cron: str,
    us_cron: str,
) -> None:
    for job_id in ("cn_open_brief", "us_open_brief"):
        if scheduler.get_job(job_id) is not None:
            scheduler.remove_job(job_id)
    if not enabled:
        return
    scheduler.add_job(
        _run_cn_open_brief_job,
        CronTrigger.from_crontab(cn_cron, timezone="Asia/Shanghai"),
        id="cn_open_brief",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_us_open_brief_job,
        CronTrigger.from_crontab(us_cron, timezone="America/New_York"),
        id="us_open_brief",
        replace_existing=True,
    )


def configure_daily_noon_brief_job(scheduler: BackgroundScheduler, enabled: bool, cron: str) -> None:
    if scheduler.get_job("daily_noon_brief") is not None:
        scheduler.remove_job("daily_noon_brief")
    if not enabled:
        return
    scheduler.add_job(
        _run_daily_noon_brief_job,
        CronTrigger.from_crontab(cron, timezone="Asia/Shanghai"),
        id="daily_noon_brief",
        replace_existing=True,
    )


def apply_collection_settings(scheduler: BackgroundScheduler) -> None:
    with Session(engine) as session:
        enabled, cron = get_collection_settings(session)
    configure_collection_job(scheduler, enabled, cron)


def apply_market_open_brief_settings(scheduler: BackgroundScheduler) -> None:
    with Session(engine) as session:
        enabled, cn_cron, us_cron = get_market_open_brief_settings(session)
    configure_market_open_brief_jobs(scheduler, enabled, cn_cron, us_cron)


def apply_daily_noon_brief_settings(scheduler: BackgroundScheduler) -> None:
    with Session(engine) as session:
        enabled, cron = get_daily_noon_brief_settings(session)
    configure_daily_noon_brief_job(scheduler, enabled, cron)


def _run_collect_all_job() -> None:
    with Session(engine) as session:
        run, locked, _ = _start_locked_job(session, "collect_all")
        if not locked:
            return
        try:
            asyncio.run(collect_all_information(session))
            asyncio.run(push_pending_alert_events(session))
            _run_due_market_open_briefs_after_collection(session)
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))
        finally:
            release_collection_job_lock()


def _run_cn_open_brief_job() -> None:
    _run_market_open_brief_job("CN", {"CN", "HK"}, "A股/港股盘中")


def _run_us_open_brief_job() -> None:
    _run_market_open_brief_job("US", {"US"}, "美股盘中")


def _run_daily_noon_brief_job() -> None:
    with Session(engine) as session:
        run, locked, waited = _start_locked_job(
            session,
            "daily_noon_brief",
            wait_seconds=BRIEF_COLLECTION_WAIT_SECONDS,
        )
        if not locked:
            return
        try:
            if _should_collect_before_brief(waited):
                asyncio.run(collect_all_information(session))
            asyncio.run(push_pending_alert_events(session))
            asyncio.run(generate_daily_brief(session, push=True, scope_label="最新24小时", latest_hours=24))
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))
        finally:
            release_collection_job_lock()


def _run_market_open_brief_job(market: str, markets: set[str], label: str) -> None:
    with Session(engine) as session:
        job_name = f"{market.lower()}_open_brief"
        run = start_job(session, job_name)
        try:
            if not is_market_trading_day(market):
                finish_job(session, run, "skipped", f"{market} market is closed")
                return
            locked, waited = _acquire_collection_lock_for_brief(run, session)
            if not locked:
                return
            try:
                if _should_collect_before_brief(waited):
                    asyncio.run(collect_all_information(session))
                asyncio.run(push_pending_alert_events(session))
                asyncio.run(generate_daily_brief(session, push=True, scope_label=label, markets=markets))
                finish_job(session, run, "success")
            finally:
                release_collection_job_lock()
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))


def _start_locked_job(session: Session, name: str, wait_seconds: float | None = None):
    run = start_job(session, name)
    locked, waited = _acquire_collection_lock(run, session, wait_seconds)
    return run, locked, waited


def _acquire_collection_lock_for_brief(run, session: Session) -> tuple[bool, bool]:
    return _acquire_collection_lock(run, session, BRIEF_COLLECTION_WAIT_SECONDS)


def _acquire_collection_lock(run, session: Session, wait_seconds: float | None = None) -> tuple[bool, bool]:
    if not acquire_collection_job_lock():
        if wait_seconds is None:
            finish_job(session, run, "skipped", "Another collection job is already running.")
            return False, False
        if not acquire_collection_job_lock(timeout=wait_seconds):
            finish_job(session, run, "skipped", "Timed out waiting for the running collection job.")
            return False, True
        return True, True
    return True, False


def _should_collect_before_brief(waited_for_collection: bool) -> bool:
    return not waited_for_collection


def _run_due_market_open_briefs_after_collection(session: Session) -> None:
    enabled, cn_cron, us_cron = get_market_open_brief_settings(session)
    if not enabled:
        return

    now = datetime.now(timezone.utc)
    due_jobs = [
        ("CN", {"CN", "HK"}, "A股/港股盘中", cn_cron, "cn_open_brief"),
        ("US", {"US"}, "美股盘中", us_cron, "us_open_brief"),
    ]
    for market, markets, label, cron, job_name in due_jobs:
        if _market_open_brief_is_due(session, market=market, cron=cron, job_name=job_name, now=now):
            _generate_market_open_brief_after_collection(session, market, markets, label, job_name)


def _generate_market_open_brief_after_collection(
    session: Session,
    market: str,
    markets: set[str],
    label: str,
    job_name: str,
) -> None:
    run = start_job(session, job_name)
    try:
        if not is_market_trading_day(market):
            finish_job(session, run, "skipped", f"{market} market is closed")
            return
        asyncio.run(generate_daily_brief(session, push=True, scope_label=label, markets=markets))
        finish_job(session, run, "success")
    except Exception as exc:
        finish_job(session, run, "failed", str(exc))


def _market_open_brief_is_due(
    session: Session,
    *,
    market: str,
    cron: str,
    job_name: str,
    now: datetime | None = None,
) -> bool:
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    market_tz = _market_timezone(market)
    now_local = now_utc.astimezone(market_tz)
    if not is_market_trading_day(market, now_local):
        return False

    due_time = _market_open_brief_time(cron)
    if due_time is None or now_local.time() < due_time:
        return False

    day_start_local = datetime.combine(now_local.date(), time.min, tzinfo=market_tz)
    day_end_local = datetime.combine(now_local.date(), time.max, tzinfo=market_tz)
    day_start_utc = day_start_local.astimezone(timezone.utc)
    day_end_utc = day_end_local.astimezone(timezone.utc)
    existing = session.exec(
        select(FetchJobRun).where(
            FetchJobRun.job_name == job_name,
            FetchJobRun.status.in_(("running", "success")),
            FetchJobRun.started_at >= day_start_utc,
            FetchJobRun.started_at <= day_end_utc,
        )
    ).first()
    return existing is None


def _market_open_brief_time(cron: str) -> time | None:
    value = cron_to_workday_time(cron)
    if not value:
        return None
    hour, minute = (int(part) for part in value.split(":", 1))
    return time(hour, minute)


def _market_timezone(market: str) -> ZoneInfo:
    if market == "US":
        return ZoneInfo("America/New_York")
    return ZoneInfo("Asia/Shanghai")
