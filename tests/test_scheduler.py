from datetime import datetime, timezone

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import FetchJobRun
from app.scheduler import (
    _market_open_brief_is_due,
    _should_collect_before_brief,
    build_scheduler,
    configure_collection_job,
    configure_daily_noon_brief_job,
    configure_market_open_brief_jobs,
)


def test_collection_job_is_registered_by_default() -> None:
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "collect_all" in job_ids
    assert "quotes" not in job_ids
    assert "market_details" not in job_ids
    assert "news" not in job_ids


def test_daily_noon_brief_job_is_registered_by_default() -> None:
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "daily_noon_brief" in job_ids


def test_market_open_brief_jobs_are_registered() -> None:
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "cn_open_brief" in job_ids
    assert "us_open_brief" in job_ids
    assert "daily_brief" not in job_ids


def test_collection_job_can_be_disabled() -> None:
    scheduler = build_scheduler()

    configure_collection_job(scheduler, False, "0 * * * *")

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "collect_all" not in job_ids


def test_market_open_brief_jobs_can_be_disabled() -> None:
    scheduler = build_scheduler()

    configure_market_open_brief_jobs(scheduler, False, "30 9 * * 1-5", "45 10 * * 1-5")

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "cn_open_brief" not in job_ids
    assert "us_open_brief" not in job_ids


def test_daily_noon_brief_job_can_be_disabled() -> None:
    scheduler = build_scheduler()

    configure_daily_noon_brief_job(scheduler, False, "0 12 * * *")

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "daily_noon_brief" not in job_ids


def test_daily_noon_brief_job_can_be_reconfigured() -> None:
    scheduler = build_scheduler()

    configure_daily_noon_brief_job(scheduler, True, "15 12 * * *")

    trigger = str(scheduler.get_job("daily_noon_brief").trigger)
    assert "hour='12'" in trigger
    assert "minute='15'" in trigger


def test_brief_job_collects_when_lock_is_available() -> None:
    assert _should_collect_before_brief(waited_for_collection=False)


def test_brief_job_skips_duplicate_collection_after_waiting_for_running_collection() -> None:
    assert not _should_collect_before_brief(waited_for_collection=True)


def test_market_open_brief_jobs_can_be_reconfigured() -> None:
    scheduler = build_scheduler()

    configure_market_open_brief_jobs(scheduler, True, "30 9 * * 1-5", "45 10 * * 1-5")

    cn_trigger = str(scheduler.get_job("cn_open_brief").trigger)
    us_trigger = str(scheduler.get_job("us_open_brief").trigger)
    assert "hour='9'" in cn_trigger
    assert "minute='30'" in cn_trigger
    assert "day_of_week='1-5'" in cn_trigger
    assert "hour='10'" in us_trigger
    assert "minute='45'" in us_trigger
    assert "day_of_week='1-5'" in us_trigger


def test_us_market_open_brief_is_due_after_open_time_when_not_run_today() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        due = _market_open_brief_is_due(
            session,
            market="US",
            cron="0 10 * * 1-5",
            job_name="us_open_brief",
            now=datetime(2026, 6, 8, 14, 5, tzinfo=timezone.utc),
        )

    assert due


def test_us_market_open_brief_is_not_due_when_already_successful_today() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            FetchJobRun(
                job_name="us_open_brief",
                status="success",
                started_at=datetime(2026, 6, 8, 14, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

        due = _market_open_brief_is_due(
            session,
            market="US",
            cron="0 10 * * 1-5",
            job_name="us_open_brief",
            now=datetime(2026, 6, 8, 14, 5, tzinfo=timezone.utc),
        )

    assert not due


def test_failed_market_open_brief_can_be_retried_today() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            FetchJobRun(
                job_name="us_open_brief",
                status="failed",
                started_at=datetime(2026, 6, 8, 14, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()

        due = _market_open_brief_is_due(
            session,
            market="US",
            cron="0 10 * * 1-5",
            job_name="us_open_brief",
            now=datetime(2026, 6, 8, 14, 5, tzinfo=timezone.utc),
        )

    assert due
