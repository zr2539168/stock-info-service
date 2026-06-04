from app.scheduler import build_scheduler, configure_market_open_brief_jobs


def test_market_open_brief_jobs_are_registered() -> None:
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "cn_open_brief" in job_ids
    assert "us_open_brief" in job_ids
    assert "daily_brief" not in job_ids


def test_market_open_brief_jobs_can_be_disabled() -> None:
    scheduler = build_scheduler()

    configure_market_open_brief_jobs(scheduler, False, "30 9 * * 1-5", "45 10 * * 1-5")

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "cn_open_brief" not in job_ids
    assert "us_open_brief" not in job_ids


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
