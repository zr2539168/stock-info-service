from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings
from app.database import get_session
from app.main import app
from app.models import (
    AlertRule,
    Brief,
    ChatSession,
    MarketIndexPoint,
    Notification,
    NotificationSubscription,
    Stock,
    User,
    UserSecret,
    UserWatchlist,
    WebLoginChallenge,
)
from app.services.notifications import (
    claim_pending_notifications,
    create_notification,
    finish_notification,
    record_subscription_result,
)
from app.services.security import SecretCipher
from app.services.users import set_deepseek_key, user_runtime_config


def test_private_brief_cannot_be_read_by_another_user() -> None:
    test_engine = _engine()
    with Session(test_engine) as session:
        first = User(openid="openid-a", status="active", role="user")
        second = User(openid="openid-b", status="active", role="user")
        session.add(first)
        session.add(second)
        session.commit()
        session.refresh(first)
        session.add(Brief(user_id=first.id, title="A 的简报", content="private"))
        session.commit()
        brief = session.exec(select(Brief)).first()

    with _client(test_engine) as client:
        response = client.get(f"/api/v1/briefs/{brief.id}", headers={"X-WX-OPENID": "openid-b"})

    assert response.status_code == 404
    assert response.json()["code"] == "ITEM_NOT_FOUND"


def test_pending_user_can_only_read_session_status() -> None:
    test_engine = _engine()
    with _client(test_engine) as client:
        status = client.get("/api/v1/session", headers={"X-WX-OPENID": "new-openid"})
        dashboard = client.get("/api/v1/dashboard", headers={"X-WX-OPENID": "new-openid"})
        profile_update = client.patch(
            "/api/v1/session",
            headers={"X-WX-OPENID": "new-openid"},
            json={"display_name": "不应保存"},
        )

    assert status.status_code == 200
    assert status.json()["user"]["status"] == "pending"
    assert status.json()["user"]["created_at"].endswith("Z")
    assert dashboard.status_code == 403
    assert dashboard.json()["code"] == "USER_NOT_ACTIVE"
    assert profile_update.status_code == 403


def test_user_watchlists_are_isolated() -> None:
    test_engine = _engine()
    with Session(test_engine) as session:
        first = User(openid="openid-a", status="active")
        second = User(openid="openid-b", status="active")
        stock = Stock(market="US", symbol="AAPL", name="Apple")
        session.add(first)
        session.add(second)
        session.add(stock)
        session.commit()
        session.refresh(first)
        session.refresh(stock)
        session.add(UserWatchlist(user_id=first.id or 0, stock_id=stock.id or 0))
        session.commit()

    with _client(test_engine) as client:
        first_result = client.get("/api/v1/watchlists", headers={"X-WX-OPENID": "openid-a"})
        second_result = client.get("/api/v1/watchlists", headers={"X-WX-OPENID": "openid-b"})

    assert len(first_result.json()["items"]) == 1
    assert second_result.json()["items"] == []


def test_all_private_resource_ids_are_checked_against_current_user() -> None:
    test_engine = _engine()
    with Session(test_engine) as session:
        owner = User(openid="owner", status="active")
        other = User(openid="other", status="active")
        stock = Stock(market="US", symbol="AAPL", name="Apple")
        session.add_all([owner, other, stock])
        session.commit()
        chat = ChatSession(user_id=owner.id)
        brief = Brief(user_id=owner.id, title="私有简报")
        alert = AlertRule(user_id=owner.id, stock_id=stock.id or 0, rule_type="price_above", threshold=100)
        notification = Notification(
            user_id=owner.id or 0,
            notification_type="alert",
            title="私有提醒",
            idempotency_key="private-notification",
        )
        session.add_all([chat, brief, alert, notification])
        session.commit()
        resource_ids = (brief.id, chat.id, alert.id, notification.id)

    headers = {"X-WX-OPENID": "other"}
    brief_id, chat_id, alert_id, notification_id = resource_ids
    with _client(test_engine) as client:
        responses = [
            client.get(f"/api/v1/briefs/{brief_id}", headers=headers),
            client.get(f"/api/v1/chat/sessions/{chat_id}/messages", headers=headers),
            client.delete(f"/api/v1/alerts/{alert_id}", headers=headers),
            client.post(f"/api/v1/notifications/{notification_id}/read", headers=headers),
        ]

    assert all(response.status_code == 404 for response in responses)
    assert all(response.json()["code"] == "ITEM_NOT_FOUND" for response in responses)


def test_non_admin_cannot_access_admin_api() -> None:
    test_engine = _engine()
    with Session(test_engine) as session:
        session.add(User(openid="normal-user", status="active", role="user"))
        session.commit()

    with _client(test_engine) as client:
        response = client.get("/api/v1/admin/users", headers={"X-WX-OPENID": "normal-user"})

    assert response.status_code == 403
    assert response.json()["code"] == "ADMIN_REQUIRED"


def test_json_api_errors_have_standard_shape() -> None:
    test_engine = _engine()
    with Session(test_engine) as session:
        session.add(User(openid="active-user", status="active"))
        session.commit()

    headers = {"X-WX-OPENID": "active-user"}
    with _client(test_engine) as client:
        invalid_range = client.get("/api/v1/indices?range=bad", headers=headers)
        invalid_payload = client.post("/api/v1/alerts", headers=headers, json={})
        missing_route = client.get("/api/v1/does-not-exist", headers=headers)

    for response in (invalid_range, invalid_payload, missing_route):
        payload = response.json()
        assert set(payload) == {"code", "message", "request_id"}
        assert payload["request_id"]
    assert invalid_payload.json()["code"] == "INVALID_REQUEST"
    assert missing_route.json()["code"] == "NOT_FOUND"


def test_ai_endpoint_explains_missing_user_key() -> None:
    test_engine = _engine()
    with Session(test_engine) as session:
        session.add(User(openid="no-key-user", status="active"))
        session.commit()

    with _client(test_engine) as client:
        response = client.post("/api/v1/indices/analyze", headers={"X-WX-OPENID": "no-key-user"})

    assert response.status_code == 422
    assert response.json()["code"] == "DEEPSEEK_KEY_REQUIRED"


def test_indices_api_supports_all_shared_ranges() -> None:
    test_engine = _engine()
    now = datetime.now(timezone.utc)
    with Session(test_engine) as session:
        session.add(User(openid="index-user", status="active"))
        session.add(
            MarketIndexPoint(
                index_code="fear_greed",
                name="恐贪指数",
                value=55,
                observed_at=now,
                content_hash="index-new",
            )
        )
        session.add(
            MarketIndexPoint(
                index_code="fear_greed",
                name="恐贪指数",
                value=25,
                observed_at=now - timedelta(days=4000),
                content_hash="index-old",
            )
        )
        session.commit()

    headers = {"X-WX-OPENID": "index-user"}
    with _client(test_engine) as client:
        payloads = {
            range_name: client.get(f"/api/v1/indices?range={range_name}", headers=headers).json()
            for range_name in ("1w", "1m", "1y", "10y", "max")
        }

    assert all(payload["range"] == range_name for range_name, payload in payloads.items())
    assert all(len(payload["cards"]) == 4 for payload in payloads.values())
    assert len(payloads["1w"]["cards"][0]["series"]) == 1
    assert len(payloads["max"]["cards"][0]["series"]) == 2


def test_user_deepseek_key_is_encrypted_and_round_trips() -> None:
    test_engine = _engine()
    old_key = settings.user_secret_master_key
    object.__setattr__(settings, "user_secret_master_key", "unit-test-master-key")
    try:
        with Session(test_engine) as session:
            user = User(openid="openid", status="active")
            session.add(user)
            session.commit()
            session.refresh(user)
            set_deepseek_key(session, user.id or 0, "sk-secret-value")
            config = user_runtime_config(session, user.id or 0)
            stored = session.exec(select(UserSecret)).first()
            assert stored is not None
            assert "sk-secret-value" not in stored.ciphertext
            assert config.deepseek_api_key == "sk-secret-value"
            assert "sk-secret-value" not in str(session.get_bind().url)
    finally:
        object.__setattr__(settings, "user_secret_master_key", old_key)

    cipher = SecretCipher("another-test-key")
    encrypted = cipher.encrypt("hello", user_id=7, kind="deepseek_api_key")
    assert encrypted.ciphertext != "hello"
    assert cipher.decrypt(
        encrypted.ciphertext,
        encrypted.nonce,
        user_id=7,
        kind="deepseek_api_key",
    ) == "hello"


def test_notification_quota_and_delivery_state() -> None:
    test_engine = _engine()
    old_template = settings.alert_template_id
    object.__setattr__(settings, "alert_template_id", "template-alert")
    try:
        with Session(test_engine) as session:
            user = User(openid="openid", status="active")
            session.add(user)
            session.commit()
            session.refresh(user)
            notification = create_notification(
                session,
                user_id=user.id or 0,
                notification_type="alert",
                title="提醒",
                content="价格达到阈值",
                page_path="/pages/alerts/detail?id=1",
                idempotency_key="test-alert-1",
            )
            assert claim_pending_notifications(session) == []
            assert session.get(Notification, notification.id).status == "no_quota"

            record_subscription_result(session, user_id=user.id or 0, template_type="alert", result="accept")
            claimed = claim_pending_notifications(session)
            assert len(claimed) == 1
            assert claimed[0]["openid"] == "openid"
            finish_notification(session, notification.id or 0, success=True)

            assert session.get(Notification, notification.id).status == "sent"
            subscription = session.exec(select(NotificationSubscription)).first()
            assert subscription.grant_count == 0
    finally:
        object.__setattr__(settings, "alert_template_id", old_template)


def test_web_login_requires_admin_confirmation_and_is_single_use() -> None:
    test_engine = _engine()
    with Session(test_engine) as session:
        session.add(User(openid="admin-openid", status="active", role="admin"))
        session.commit()

    with _client(test_engine) as client:
        login = client.get("/admin/login")
        assert login.status_code == 200
        with Session(test_engine) as session:
            challenge = session.exec(select(WebLoginChallenge)).first()
            expires_at = challenge.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            assert expires_at <= datetime.now(timezone.utc) + timedelta(minutes=3)

        confirmation = client.post(
            f"/api/v1/admin/web-login/{challenge.id}/confirm",
            headers={"X-WX-OPENID": "admin-openid"},
        )
        assert confirmation.status_code == 200

        status = client.get(f"/admin/login/status/{challenge.id}")
        assert status.json()["status"] == "authenticated"
        assert client.cookies.get("admin_session")

        repeated = client.post(
            f"/api/v1/admin/web-login/{challenge.id}/confirm",
            headers={"X-WX-OPENID": "admin-openid"},
        )
        assert repeated.status_code == 409


def test_web_login_can_be_explicitly_cancelled() -> None:
    test_engine = _engine()
    with Session(test_engine) as session:
        session.add(User(openid="cancel-admin", status="active", role="admin"))
        session.commit()

    headers = {"X-WX-OPENID": "cancel-admin"}
    with _client(test_engine) as client:
        assert client.get("/admin/login").status_code == 200
        with Session(test_engine) as session:
            challenge = session.exec(select(WebLoginChallenge)).first()
            challenge_id = challenge.id
        cancelled = client.post(f"/api/v1/admin/web-login/{challenge_id}/cancel", headers=headers)
        status = client.get(f"/admin/login/status/{challenge_id}")
        repeated = client.post(f"/api/v1/admin/web-login/{challenge_id}/confirm", headers=headers)

    assert cancelled.status_code == 200
    assert status.json()["status"] == "cancelled"
    assert repeated.status_code == 409


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _client(test_engine):
    def override_session():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    class ClientContext:
        def __enter__(self):
            return client.__enter__()

        def __exit__(self, exc_type, exc, traceback):
            try:
                return client.__exit__(exc_type, exc, traceback)
            finally:
                app.dependency_overrides.pop(get_session, None)

    return ClientContext()
