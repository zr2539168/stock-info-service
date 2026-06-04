from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.main import app
from app.models import AlertRule, Stock
from fastapi.testclient import TestClient


def test_delete_alert_rule_route_removes_rule() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        stock = Stock(market="US", symbol="GOOGL", name="Alphabet Inc.")
        session.add(stock)
        session.commit()
        session.refresh(stock)
        rule = AlertRule(stock_id=stock.id or 0, rule_type="price_below", threshold=365)
        session.add(rule)
        session.commit()
        session.refresh(rule)
        rule_id = rule.id

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.post(f"/alerts/{rule_id}/delete", follow_redirects=False)
        with Session(engine) as session:
            remaining = session.exec(select(AlertRule)).all()
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 303
    assert remaining == []
