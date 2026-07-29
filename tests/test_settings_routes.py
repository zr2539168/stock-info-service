from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import AppSetting
from fastapi.testclient import TestClient


def test_settings_page_saves_global_collection_switch_only() -> None:
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
                    "collection_enabled": "true",
                },
                follow_redirects=False,
            )
        with Session(engine) as session:
            enabled = session.get(AppSetting, "collection_enabled")
            cron = session.get(AppSetting, "collect_all_cron")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 303
    assert enabled is not None
    assert enabled.value == "true"
    assert cron is not None
    assert cron.value == "0 * * * *"
