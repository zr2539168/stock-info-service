from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import AppSetting
from fastapi.testclient import TestClient


def test_settings_page_saves_custom_daily_noon_brief_time() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/settings",
                data={
                    "deepseek_base_url": "https://deepseek.test",
                    "deepseek_model": "deepseek-v4-flash",
                    "pushdeer_endpoint": "https://pushdeer.test/message/push",
                    "collection_enabled": "true",
                    "daily_noon_brief_enabled": "true",
                    "daily_noon_brief_time": "13:20",
                    "market_open_briefs_enabled": "true",
                    "cn_open_brief_time": "10:00",
                    "us_open_brief_time": "10:00",
                },
                follow_redirects=False,
            )
        with Session(engine) as session:
            enabled = session.get(AppSetting, "daily_noon_brief_enabled")
            cron = session.get(AppSetting, "daily_noon_brief_cron")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 303
    assert enabled is not None
    assert enabled.value == "true"
    assert cron is not None
    assert cron.value == "20 13 * * *"
