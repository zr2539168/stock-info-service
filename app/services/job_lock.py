from __future__ import annotations

import socket
from threading import Lock
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import DistributedJobLock


collection_job_lock = Lock()
_lease_owner = f"{socket.gethostname()}:{uuid4().hex}"


def acquire_collection_job_lock(timeout: float | None = None) -> bool:
    if timeout is None:
        return collection_job_lock.acquire(blocking=False)
    return collection_job_lock.acquire(timeout=timeout)


def release_collection_job_lock() -> None:
    if collection_job_lock.locked():
        collection_job_lock.release()


def acquire_job_lease(session: Session, lock_key: str, ttl_seconds: int = 900) -> str | None:
    """获取跨实例任务租约；返回 owner 表示成功，None 表示被其他实例持有。"""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=max(30, ttl_seconds))
    candidate_owner = f"{_lease_owner}:{uuid4().hex}"
    try:
        stmt = select(DistributedJobLock).where(DistributedJobLock.lock_key == lock_key)
        if session.get_bind().dialect.name != "sqlite":
            stmt = stmt.with_for_update()
        item = session.exec(stmt).first()
        if item is None:
            item = DistributedJobLock(lock_key=lock_key, owner=candidate_owner, expires_at=expires_at)
        elif _as_utc(item.expires_at) > now:
            session.rollback()
            return None
        else:
            item.owner = candidate_owner
            item.expires_at = expires_at
            item.updated_at = now
        session.add(item)
        session.commit()
        return candidate_owner
    except IntegrityError:
        session.rollback()
        return None


def renew_job_lease(session: Session, lock_key: str, owner: str, ttl_seconds: int = 900) -> bool:
    item = session.get(DistributedJobLock, lock_key)
    if item is None or item.owner != owner:
        return False
    item.expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(30, ttl_seconds))
    item.updated_at = datetime.now(timezone.utc)
    session.add(item)
    session.commit()
    return True


def release_job_lease(session: Session, lock_key: str, owner: str) -> None:
    item = session.get(DistributedJobLock, lock_key)
    if item is None or item.owner != owner:
        return
    item.expires_at = datetime.now(timezone.utc)
    item.updated_at = datetime.now(timezone.utc)
    session.add(item)
    session.commit()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
