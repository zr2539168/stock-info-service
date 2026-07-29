from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Brief, FetchJobRun, Notification, User, UserPreference
from app.services.user_scheduler import run_due_user_briefs


def test_due_user_brief_is_idempotent_for_same_schedule_day(tmp_path, monkeypatch) -> None:
    import app.services.user_scheduler as user_scheduler

    engine = create_engine(f"sqlite:///{(tmp_path / 'briefs.db').as_posix()}")
    SQLModel.metadata.create_all(engine)
    now = datetime(2026, 7, 28, 5, 5, tzinfo=timezone.utc)  # 上海时间 13:05

    async def fake_generate(session, *, user_id, **kwargs):
        brief = Brief(user_id=user_id, title="定时简报", content="测试")
        session.add(brief)
        session.commit()
        session.refresh(brief)
        session.add(
            Notification(
                user_id=user_id,
                notification_type="brief",
                title=brief.title,
                idempotency_key=f"brief:{brief.id}",
            )
        )
        session.commit()
        return brief

    monkeypatch.setattr(user_scheduler, "has_deepseek_key", lambda session, user_id: True)
    monkeypatch.setattr(user_scheduler, "generate_daily_brief", fake_generate)

    with Session(engine) as session:
        user = User(openid="brief-user", status="active")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.add(UserPreference(user_id=user.id or 0, daily_brief_enabled=True, daily_brief_time="13:00"))
        session.commit()

        assert asyncio.run(run_due_user_briefs(session, now=now)) == 1
        assert asyncio.run(run_due_user_briefs(session, now=now)) == 0

        assert len(session.exec(select(Brief).where(Brief.user_id == user.id)).all()) == 1
        assert len(session.exec(select(Notification).where(Notification.user_id == user.id)).all()) == 1
        runs = session.exec(
            select(FetchJobRun).where(FetchJobRun.idempotency_key == f"user-brief:{user.id}:daily:2026-07-28")
        ).all()
        assert len(runs) == 1
        assert runs[0].status == "success"


def test_due_user_brief_without_key_is_skipped_once(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'briefs-missing-key.db').as_posix()}")
    SQLModel.metadata.create_all(engine)
    now = datetime(2026, 7, 28, 5, 5, tzinfo=timezone.utc)

    with Session(engine) as session:
        user = User(openid="no-key-user", status="active")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.add(UserPreference(user_id=user.id or 0, daily_brief_enabled=True, daily_brief_time="13:00"))
        session.commit()

        assert asyncio.run(run_due_user_briefs(session, now=now)) == 0
        assert asyncio.run(run_due_user_briefs(session, now=now)) == 0
        runs = session.exec(select(FetchJobRun).where(FetchJobRun.user_id == user.id)).all()
        assert len(runs) == 1
        assert runs[0].status == "skipped"
        assert "Key 未配置" in runs[0].error
