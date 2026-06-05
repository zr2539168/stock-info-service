from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.main import app
from app.models import ChatMessage, ChatSession
from fastapi.testclient import TestClient


def test_chat_page_can_open_selected_history_session() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        old = ChatSession(title="旧对话")
        latest = ChatSession(title="最新对话")
        session.add(old)
        session.add(latest)
        session.commit()
        session.refresh(old)
        session.refresh(latest)
        session.add(ChatMessage(session_id=old.id or 0, role="user", content="旧问题"))
        session.add(ChatMessage(session_id=latest.id or 0, role="user", content="新问题"))
        session.commit()
        old_id = old.id

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.get(f"/chat?session_id={old_id}")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    assert "旧问题" in response.text
    assert "新问题" not in response.text
    assert f'name="session_id" value="{old_id}"' in response.text


def test_chat_post_continues_selected_history_session(monkeypatch) -> None:
    import app.main as main

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    async def fake_answer_question(session, question: str) -> str:
        return "AI回答"

    monkeypatch.setattr(main, "answer_question", fake_answer_question)

    with Session(engine) as session:
        old = ChatSession(title="旧对话")
        latest = ChatSession(title="最新对话")
        session.add(old)
        session.add(latest)
        session.commit()
        session.refresh(old)
        session.refresh(latest)
        old_id = old.id
        latest_id = latest.id

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/chat",
                data={"session_id": str(old_id), "question": "继续旧对话"},
                follow_redirects=False,
            )
        with Session(engine) as session:
            old_messages = session.exec(select(ChatMessage).where(ChatMessage.session_id == old_id)).all()
            latest_messages = session.exec(select(ChatMessage).where(ChatMessage.session_id == latest_id)).all()
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 303
    assert response.headers["location"] == f"/chat?session_id={old_id}"
    assert [item.content for item in old_messages] == ["继续旧对话", "AI回答"]
    assert latest_messages == []
