from app.services.job_lock import acquire_collection_job_lock, release_collection_job_lock


def test_collection_lock_can_wait_for_running_job() -> None:
    assert acquire_collection_job_lock()
    try:
        assert not acquire_collection_job_lock(timeout=0)
    finally:
        release_collection_job_lock()

    assert acquire_collection_job_lock(timeout=0.1)
    release_collection_job_lock()
