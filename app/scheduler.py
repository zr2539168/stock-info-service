from __future__ import annotations

import asyncio

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session

from app.config import settings
from app.database import engine
from app.services.market_calendar import is_market_trading_day
from app.services.collector import (
    collect_all_information,
    collect_announcements,
    collect_market_details,
    collect_macro,
    collect_news,
    collect_quotes,
    finish_job,
    generate_daily_brief,
    push_pending_alert_events,
    start_job,
)


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(_run_quotes_job, CronTrigger.from_crontab(settings.fetch_quotes_cron), id="quotes", replace_existing=True)
    scheduler.add_job(
        _run_market_details_job,
        CronTrigger.from_crontab(settings.fetch_quotes_cron),
        id="market_details",
        replace_existing=True,
    )
    scheduler.add_job(_run_news_job, CronTrigger.from_crontab(settings.fetch_news_cron), id="news", replace_existing=True)
    scheduler.add_job(
        _run_announcements_job,
        CronTrigger.from_crontab(settings.fetch_news_cron),
        id="announcements",
        replace_existing=True,
    )
    scheduler.add_job(_run_macro_job, CronTrigger.from_crontab(settings.fetch_macro_cron), id="macro", replace_existing=True)
    scheduler.add_job(_run_brief_job, CronTrigger.from_crontab(settings.daily_brief_cron), id="daily_brief", replace_existing=True)
    if settings.market_open_briefs_enabled:
        scheduler.add_job(
            _run_cn_open_brief_job,
            CronTrigger.from_crontab(settings.cn_open_brief_cron, timezone="Asia/Shanghai"),
            id="cn_open_brief",
            replace_existing=True,
        )
        scheduler.add_job(
            _run_us_open_brief_job,
            CronTrigger.from_crontab(settings.us_open_brief_cron, timezone="America/New_York"),
            id="us_open_brief",
            replace_existing=True,
        )
    return scheduler


def _run_quotes_job() -> None:
    with Session(engine) as session:
        run = start_job(session, "quotes")
        try:
            asyncio.run(collect_quotes(session))
            asyncio.run(push_pending_alert_events(session))
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))


def _run_market_details_job() -> None:
    with Session(engine) as session:
        run = start_job(session, "market_details")
        try:
            asyncio.run(collect_market_details(session))
            asyncio.run(push_pending_alert_events(session))
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))


def _run_news_job() -> None:
    with Session(engine) as session:
        run = start_job(session, "news")
        try:
            asyncio.run(collect_news(session))
            asyncio.run(push_pending_alert_events(session))
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))


def _run_announcements_job() -> None:
    with Session(engine) as session:
        run = start_job(session, "announcements")
        try:
            asyncio.run(collect_announcements(session))
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))


def _run_macro_job() -> None:
    with Session(engine) as session:
        run = start_job(session, "macro")
        try:
            asyncio.run(collect_macro(session))
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))


def _run_brief_job() -> None:
    with Session(engine) as session:
        run = start_job(session, "daily_brief")
        try:
            asyncio.run(collect_all_information(session))
            asyncio.run(push_pending_alert_events(session))
            asyncio.run(generate_daily_brief(session, push=True))
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))


def _run_cn_open_brief_job() -> None:
    _run_market_open_brief_job("CN", "A股开盘半小时后")


def _run_us_open_brief_job() -> None:
    _run_market_open_brief_job("US", "美股开盘半小时后")


def _run_market_open_brief_job(market: str, label: str) -> None:
    with Session(engine) as session:
        run = start_job(session, f"{market.lower()}_open_brief")
        try:
            if not is_market_trading_day(market):
                finish_job(session, run, "skipped", f"{market} market is closed")
                return
            asyncio.run(collect_all_information(session))
            asyncio.run(push_pending_alert_events(session))
            asyncio.run(generate_daily_brief(session, push=True, scope_label=label))
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))
