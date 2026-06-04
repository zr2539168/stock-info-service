from __future__ import annotations

import asyncio

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session

from app.config import settings
from app.database import engine
from app.services.collector import (
    collect_macro,
    collect_news,
    collect_quotes,
    finish_job,
    generate_daily_brief,
    start_job,
)


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(_run_quotes_job, CronTrigger.from_crontab(settings.fetch_quotes_cron), id="quotes", replace_existing=True)
    scheduler.add_job(_run_news_job, CronTrigger.from_crontab(settings.fetch_news_cron), id="news", replace_existing=True)
    scheduler.add_job(_run_macro_job, CronTrigger.from_crontab(settings.fetch_macro_cron), id="macro", replace_existing=True)
    scheduler.add_job(_run_brief_job, CronTrigger.from_crontab(settings.daily_brief_cron), id="daily_brief", replace_existing=True)
    return scheduler


def _run_quotes_job() -> None:
    with Session(engine) as session:
        run = start_job(session, "quotes")
        try:
            collect_quotes(session)
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))


def _run_news_job() -> None:
    with Session(engine) as session:
        run = start_job(session, "news")
        try:
            asyncio.run(collect_news(session))
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
            asyncio.run(generate_daily_brief(session, push=True))
            finish_job(session, run, "success")
        except Exception as exc:
            finish_job(session, run, "failed", str(exc))

