from app.scheduler import build_scheduler


def test_market_open_brief_jobs_are_registered() -> None:
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "cn_open_brief" in job_ids
    assert "us_open_brief" in job_ids
