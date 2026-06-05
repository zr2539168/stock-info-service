from __future__ import annotations

import asyncio

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session

from app.config import settings
from app.database import engine
from app.services.job_lock import acquire_collection_job_lock, release_collection_job_lock
from app.services.market_calendar import is_market_trading_day
from app.services.settings_service import (
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
        run, locked = _start_locked_job(session, "collect_all")
        if not locked:
            return
        try:
            asyncio.run(collect_all_information(session))
            asyncio.run(push_pending_alert_events(session))
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
        run, locked = _start_locked_job(session, "daily_noon_brief")
        if not locked:
            return
        try:
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
        run = start_job(session, f"{market.lower()}_open_brief")
        try:
            if not is_market_trading_day(market):
                finish_job(session, run, "skipped", f"{market} market is closed")
                return
            asyncio.run(generate_daily_brief(session, push=True, scope_label=label, markets=markets))
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))


def _start_locked_job(session: Session, name: str):
    run = start_job(session, name)
    if not acquire_collection_job_lock():
        finish_job(session, run, "skipped", "Another collection job is already running.")
        return run, False
    return run, True
