from sqlmodel import Session, SQLModel, create_engine

from app.services.job_lock import (
    acquire_collection_job_lock,
    acquire_job_lease,
    release_collection_job_lock,
    release_job_lease,
)


def test_collection_lock_can_wait_for_running_job() -> None:
    assert acquire_collection_job_lock()
    try:
        assert not acquire_collection_job_lock(timeout=0)
    finally:
        release_collection_job_lock()

    assert acquire_collection_job_lock(timeout=0.1)
    release_collection_job_lock()


def test_database_lease_allows_only_one_owner(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'lease.db').as_posix()}")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as first, Session(engine) as second:
        owner = acquire_job_lease(first, "scheduled:test", ttl_seconds=60)
        assert owner
        assert acquire_job_lease(second, "scheduled:test", ttl_seconds=60) is None
        release_job_lease(first, "scheduled:test", owner)
        next_owner = acquire_job_lease(second, "scheduled:test", ttl_seconds=60)
        assert next_owner
        assert next_owner != owner
