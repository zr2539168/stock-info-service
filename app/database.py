from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings


def _ensure_sqlite_parent(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    db_path = database_url.replace("sqlite:///", "", 1)
    if db_path == ":memory:":
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent(settings.database_url)
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


def init_db() -> None:
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _migrate_alert_rule_push_mode()
    _mark_interrupted_jobs()


def _migrate_alert_rule_push_mode() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "alertrule" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("alertrule")}
    if "push_mode" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE alertrule ADD COLUMN push_mode VARCHAR(32) NOT NULL DEFAULT 'cooldown'"))


def _mark_interrupted_jobs() -> None:
    from app.models import FetchJobRun

    with Session(engine) as session:
        jobs = session.exec(select(FetchJobRun).where(FetchJobRun.status == "running")).all()
        for job in jobs:
            job.status = "failed"
            job.ended_at = datetime.now(timezone.utc)
            job.error = job.error or "Service restarted before this job completed."
            session.add(job)
        session.commit()


def get_session() -> Session:
    with Session(engine) as session:
        yield session

