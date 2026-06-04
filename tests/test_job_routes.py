from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app
from app.models import FetchJobRun
from fastapi.testclient import TestClient


def test_current_jobs_route_returns_running_jobs() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(FetchJobRun(job_name="manual_brief", status="running"))
        session.commit()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.get("/jobs/current")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["running"][0]["job_name"] == "manual_brief"
    assert payload["running"][0]["label"] == "抓取信息并生成 AI 简报"


def test_progress_job_request_returns_job_id(monkeypatch) -> None:
    import app.main as main

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    async def fake_collect_macro(session):
        return 1

    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "collect_macro", fake_collect_macro)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.post("/jobs/run/macro", headers={"X-Progress-Request": "1"})
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] is not None
    assert payload["redirect_url"] == "/jobs"
