from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, inspect, select as sa_select
from sqlmodel import Session, select

from app.database import normalize_database_url
from app.models import AppSetting, Stock, User, UserPreference, UserWatchlist
from app.services.content import content_hash
from app.services.settings_service import cron_to_daily_time, cron_to_workday_time


SHARED_TABLES = (
    "marketquote",
    "tradingdata",
    "historicalprice",
    "orderbooksnapshot",
    "institutionalflow",
    "newsitem",
    "announcement",
    "macroevent",
    "marketindexpoint",
)

PRIVATE_TABLES = (
    "brief",
    "chatsession",
    "chatmessage",
    "alertrule",
    "alertevent",
    "marketindexanalysis",
    "aiusagelog",
    "fetchjobrun",
)

GLOBAL_SETTING_KEYS = {"collection_enabled", "collect_all_cron"}
DISCARDED_SETTING_KEYS = {"deepseek_api_key", "pushdeer_pushkey", "pushdeer_endpoint"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将本地 SQLite 数据迁移到 CloudBase MySQL")
    parser.add_argument("--source-sqlite", default="data/stock_info.db", help="源 SQLite 文件")
    parser.add_argument("--target-dsn", required=True, help="目标 MySQL SQLAlchemy DSN")
    parser.add_argument("--admin-openid", required=True, help="接收本地私有数据的首位管理员 OpenID")
    parser.add_argument("--dry-run", action="store_true", help="执行完整检查和计数，但回滚目标数据库写入")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = Path(args.source_sqlite).resolve()
    if not source_path.is_file():
        raise SystemExit(f"源 SQLite 文件不存在：{source_path}")
    source_engine = create_engine(f"sqlite:///{source_path.as_posix()}")
    target_engine = create_engine(normalize_database_url(args.target_dsn), pool_pre_ping=True)
    required_target_tables = {"app_user", "user_watchlist", "user_preference", *SHARED_TABLES, *PRIVATE_TABLES}
    missing = required_target_tables - set(inspect(target_engine).get_table_names())
    if missing:
        raise SystemExit(f"目标数据库结构未初始化，请先执行 alembic upgrade head。缺少：{', '.join(sorted(missing))}")

    source_meta = MetaData()
    source_meta.reflect(bind=source_engine)
    target_meta = MetaData()
    target_meta.reflect(bind=target_engine)
    counts: dict[str, int] = defaultdict(int)

    with source_engine.connect() as source_conn, target_engine.connect() as target_conn:
        transaction = target_conn.begin()
        try:
            with Session(bind=target_conn) as target_session:
                admin = _ensure_admin(target_session, args.admin_openid)
                stock_map = _migrate_stocks(
                    source_conn,
                    source_meta,
                    target_session,
                    admin.id or 0,
                    counts,
                )
                for table_name in SHARED_TABLES:
                    _copy_table(
                        source_conn,
                        target_conn,
                        source_meta,
                        target_meta,
                        table_name,
                        counts,
                        stock_map=stock_map,
                    )
                for table_name in PRIVATE_TABLES:
                    _copy_table(
                        source_conn,
                        target_conn,
                        source_meta,
                        target_meta,
                        table_name,
                        counts,
                        stock_map=stock_map,
                        owner_user_id=admin.id,
                    )
                _migrate_settings(source_conn, source_meta, target_session, admin.id or 0, counts)
                target_session.commit()
            if args.dry_run:
                transaction.rollback()
            else:
                transaction.commit()
        except Exception:
            transaction.rollback()
            raise

    mode = "DRY-RUN（已回滚）" if args.dry_run else "已提交"
    print(f"迁移完成：{mode}")
    for name in sorted(counts):
        print(f"  {name}: {counts[name]}")
    print("PushDeer 配置和所有旧 DeepSeek Key 均未迁移。")
    return 0


def _ensure_admin(session: Session, openid: str) -> User:
    admin = session.exec(select(User).where(User.openid == openid)).first()
    now = datetime.now(timezone.utc)
    if admin is None:
        admin = User(openid=openid, status="active", role="admin", approved_at=now)
        session.add(admin)
        session.flush()
    else:
        admin.status = "active"
        admin.role = "admin"
        admin.approved_at = admin.approved_at or now
        session.add(admin)
        session.flush()
    return admin


def _migrate_stocks(
    source_conn,
    source_meta: MetaData,
    session: Session,
    admin_user_id: int,
    counts: dict[str, int],
) -> dict[int, int]:
    source_table = source_meta.tables.get("stock")
    if source_table is None:
        return {}
    stock_map: dict[int, int] = {}
    for row in source_conn.execute(sa_select(source_table)).mappings():
        stock = session.exec(
            select(Stock).where(Stock.market == row["market"], Stock.symbol == row["symbol"])
        ).first()
        if stock is None:
            stock = Stock(
                market=row["market"],
                symbol=row["symbol"],
                name=row.get("name", "") or "",
                tags="",
                active=bool(row.get("active", True)),
                created_at=row.get("created_at") or datetime.now(timezone.utc),
            )
            session.add(stock)
            session.flush()
            counts["stock"] += 1
        stock_map[int(row["id"])] = stock.id or 0
        relation = session.exec(
            select(UserWatchlist).where(
                UserWatchlist.user_id == admin_user_id,
                UserWatchlist.stock_id == stock.id,
            )
        ).first()
        if relation is None:
            session.add(
                UserWatchlist(
                    user_id=admin_user_id,
                    stock_id=stock.id or 0,
                    tags=row.get("tags", "") or "",
                    active=bool(row.get("active", True)),
                    created_at=row.get("created_at") or datetime.now(timezone.utc),
                )
            )
            session.flush()
            counts["user_watchlist"] += 1
    return stock_map


def _copy_table(
    source_conn,
    target_conn,
    source_meta: MetaData,
    target_meta: MetaData,
    table_name: str,
    counts: dict[str, int],
    *,
    stock_map: dict[int, int],
    owner_user_id: int | None = None,
) -> None:
    source_table = source_meta.tables.get(table_name)
    target_table = target_meta.tables.get(table_name)
    if source_table is None or target_table is None:
        return
    target_columns = set(target_table.c.keys())
    for row in source_conn.execute(sa_select(source_table)).mappings():
        payload = {key: value for key, value in dict(row).items() if key in target_columns}
        if "stock_id" in payload and payload["stock_id"] is not None:
            payload["stock_id"] = stock_map.get(int(payload["stock_id"]), payload["stock_id"])
        _refresh_content_hash(table_name, payload)
        if owner_user_id is not None and "user_id" in target_columns:
            payload["user_id"] = owner_user_id
        content_hash_value = payload.get("content_hash")
        if content_hash_value and "content_hash" in target_table.c:
            duplicate = target_conn.execute(
                sa_select(target_table.c.content_hash)
                .where(target_table.c.content_hash == content_hash_value)
                .limit(1)
            ).first()
            if duplicate is not None:
                continue
        primary_key = payload.get("id")
        if primary_key is not None and "id" in target_table.c:
            exists = target_conn.execute(
                sa_select(target_table.c.id).where(target_table.c.id == primary_key).limit(1)
            ).first()
            if exists is not None:
                continue
        target_conn.execute(target_table.insert().values(**payload))
        counts[table_name] += 1


def _refresh_content_hash(table_name: str, payload: dict[str, Any]) -> None:
    if "content_hash" not in payload:
        return
    if table_name == "historicalprice":
        payload["content_hash"] = content_hash(
            str(payload.get("stock_id") or ""),
            _utc_isoformat(payload["trade_date"]),
            str(payload.get("source") or ""),
        )
    elif table_name in {"newsitem", "announcement", "macroevent"}:
        identity = str(payload.get("url") or "").strip() or str(payload.get("title") or "").strip()
        payload["content_hash"] = content_hash(str(payload.get("stock_id") or ""), identity)
    elif table_name == "marketindexpoint":
        payload["content_hash"] = content_hash(
            str(payload.get("index_code") or ""),
            payload["observed_at"].date().isoformat(),
        )


def _utc_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _migrate_settings(
    source_conn,
    source_meta: MetaData,
    session: Session,
    admin_user_id: int,
    counts: dict[str, int],
) -> None:
    table = source_meta.tables.get("appsetting")
    values: dict[str, str] = {}
    if table is not None:
        for row in source_conn.execute(sa_select(table)).mappings():
            key = str(row["key"])
            if key in DISCARDED_SETTING_KEYS:
                continue
            values[key] = str(row.get("value", ""))
            if key in GLOBAL_SETTING_KEYS and session.get(AppSetting, key) is None:
                session.add(AppSetting(key=key, value=values[key], secret=False))
                counts["appsetting"] += 1
    preference = session.get(UserPreference, admin_user_id)
    created_preference = preference is None
    if preference is None:
        preference = UserPreference(user_id=admin_user_id)
    preference.daily_brief_enabled = _as_bool(values.get("daily_noon_brief_enabled", "false"))
    preference.market_open_briefs_enabled = _as_bool(values.get("market_open_briefs_enabled", "false"))
    preference.daily_brief_time = cron_to_daily_time(values.get("daily_noon_brief_cron", "")) or "12:00"
    preference.cn_open_brief_time = cron_to_workday_time(values.get("cn_open_brief_cron", "")) or "10:00"
    preference.us_open_brief_time = cron_to_workday_time(values.get("us_open_brief_cron", "")) or "10:00"
    model = values.get("deepseek_model", "")
    if model:
        preference.deepseek_model = model
    session.add(preference)
    if created_preference:
        counts["user_preference"] += 1


def _as_bool(value: Any) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
