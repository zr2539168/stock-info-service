from __future__ import annotations

from threading import Lock


collection_job_lock = Lock()


def acquire_collection_job_lock() -> bool:
    return collection_job_lock.acquire(blocking=False)


def release_collection_job_lock() -> None:
    if collection_job_lock.locked():
        collection_job_lock.release()
