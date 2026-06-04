from sqlmodel import Session, SQLModel, create_engine

from app.models import AppSetting
from app.services.settings_service import get_runtime_config, set_setting


def test_runtime_config_uses_database_override() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        set_setting(session, "deepseek_model", "deepseek-v4-pro")
        set_setting(session, "pushdeer_endpoint", "https://example.test/push")

        cfg = get_runtime_config(session)

        assert cfg.deepseek_model == "deepseek-v4-pro"
        assert cfg.pushdeer_endpoint == "https://example.test/push"
        assert session.get(AppSetting, "deepseek_model") is not None

