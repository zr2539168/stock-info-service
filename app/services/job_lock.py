from __future__ import annotations

from threading import Lock


collection_job_lock = Lock()


def acquire_collection_job_lock(timeout: float | None = None) -> bool:
    if timeout is None:
        return collection_job_lock.acquire(blocking=False)
    return collection_job_lock.acquire(timeout=timeout)


def release_collection_job_lock() -> None:
    if collection_job_lock.locked():
        collection_job_lock.release()
