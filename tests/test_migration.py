from __future__ import annotations

import sys
from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import AppSetting, Brief, HistoricalPrice, Stock, User, UserPreference, UserWatchlist
from app.services.content import content_hash
from scripts import migrate_sqlite_to_mysql as migration


def test_sqlite_migration_supports_dry_run_and_idempotent_import(tmp_path, monkeypatch, capsys) -> None:
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    source_engine = create_engine(f"sqlite:///{source_path.as_posix()}")
    target_engine = create_engine(f"sqlite:///{target_path.as_posix()}")
    SQLModel.metadata.create_all(source_engine)
    SQLModel.metadata.create_all(target_engine)

    with Session(source_engine) as source:
        stock = Stock(market="US", symbol="AAPL", name="Apple", tags="核心")
        source.add(stock)
        source.commit()
        source.refresh(stock)
        source.add(
            HistoricalPrice(
                stock_id=stock.id or 0,
                trade_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
                close=200,
                source="test",
                content_hash="old-source-hash",
            )
        )
        source.add(Brief(title="旧简报", content="正文", scope_key="all"))
        source.add(AppSetting(key="daily_noon_brief_enabled", value="true"))
        source.add(AppSetting(key="daily_noon_brief_cron", value="20 13 * * *"))
        source.add(AppSetting(key="deepseek_api_key", value="must-not-migrate", secret=True))
        source.commit()

    base_args = [
        "migrate_sqlite_to_mysql.py",
        "--source-sqlite",
        str(source_path),
        "--target-dsn",
        f"sqlite:///{target_path.as_posix()}",
        "--admin-openid",
        "admin-openid",
    ]
    monkeypatch.setattr(sys, "argv", [*base_args, "--dry-run"])
    assert migration.main() == 0
    with Session(target_engine) as target:
        assert target.exec(select(User)).first() is None

    monkeypatch.setattr(sys, "argv", base_args)
    assert migration.main() == 0
    assert migration.main() == 0
    output = capsys.readouterr().out
    assert "DRY-RUN（已回滚）" in output
    assert "PushDeer 配置和所有旧 DeepSeek Key 均未迁移" in output

    with Session(target_engine) as target:
        admin = target.exec(select(User).where(User.openid == "admin-openid")).one()
        watchlists = target.exec(select(UserWatchlist).where(UserWatchlist.user_id == admin.id)).all()
        briefs = target.exec(select(Brief).where(Brief.user_id == admin.id)).all()
        prices = target.exec(select(HistoricalPrice)).all()
        preference = target.get(UserPreference, admin.id)
        discarded = target.get(AppSetting, "deepseek_api_key")
        assert admin.role == "admin"
        assert len(watchlists) == 1
        assert len(briefs) == 1
        assert len(prices) == 1
        assert prices[0].stock_id == watchlists[0].stock_id
        assert prices[0].content_hash == content_hash(
            str(watchlists[0].stock_id),
            datetime(2026, 7, 1, tzinfo=timezone.utc).isoformat(),
            "test",
        )
        assert preference is not None
        assert preference.daily_brief_enabled
        assert preference.daily_brief_time == "13:20"
        assert discarded is None
