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


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("mysql://"):
        return database_url.replace("mysql://", "mysql+pymysql://", 1)
    return database_url


database_url = normalize_database_url(settings.database_url)
_ensure_sqlite_parent(database_url)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(
    database_url,
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=not database_url.startswith("sqlite"),
    pool_recycle=1800,
)


def init_db() -> None:
    from app import models  # noqa: F401

    if database_url.startswith("sqlite"):
        SQLModel.metadata.create_all(engine)
        _migrate_alert_rule_push_mode()
        _migrate_brief_scope_key()
        _migrate_volume_analysis_columns()
        _migrate_multi_user_columns()
    else:
        tables = set(inspect(engine).get_table_names())
        required = {"app_user", "stock", "alembic_version"}
        if not required.issubset(tables):
            missing = ", ".join(sorted(required - tables))
            raise RuntimeError(f"生产数据库尚未完成 Alembic 初始化，缺少表：{missing}")
    _mark_interrupted_jobs()


def _migrate_alert_rule_push_mode() -> None:
    if not database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "alertrule" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("alertrule")}
    if "push_mode" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE alertrule ADD COLUMN push_mode VARCHAR(32) NOT NULL DEFAULT 'cooldown'"))


def _migrate_brief_scope_key() -> None:
    if not database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "brief" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("brief")}
    if "scope_key" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE brief ADD COLUMN scope_key VARCHAR(128) NOT NULL DEFAULT ''"))


def _migrate_volume_analysis_columns() -> None:
    if not database_url.startswith("sqlite"):
        return
    for table_name in ("marketquote", "tradingdata"):
        _add_sqlite_column_if_missing(table_name, "volume_ratio", "REAL")
        _add_sqlite_column_if_missing(table_name, "volume_signal", "VARCHAR(32) NOT NULL DEFAULT ''")


def _add_sqlite_column_if_missing(table_name: str, column_name: str, column_sql: str) -> None:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))


def _migrate_multi_user_columns() -> None:
    if not database_url.startswith("sqlite"):
        return
    owner_tables = (
        "marketindexanalysis",
        "brief",
        "chatsession",
        "alertrule",
        "alertevent",
        "fetchjobrun",
        "aiusagelog",
    )
    for table_name in owner_tables:
        _add_sqlite_column_if_missing(table_name, "user_id", "INTEGER")
    _add_sqlite_column_if_missing("fetchjobrun", "idempotency_key", "VARCHAR(255) NOT NULL DEFAULT ''")


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

