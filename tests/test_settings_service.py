from sqlmodel import Session, SQLModel, create_engine

from app.models import AppSetting
import pytest

from app.services.settings_service import (
    cron_to_workday_time,
    daily_time_to_cron,
    cron_to_daily_time,
    get_collection_settings,
    get_daily_noon_brief_settings,
    get_market_open_brief_settings,
    get_runtime_config,
    set_setting,
    workday_time_to_cron,
)


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


def test_market_open_brief_settings_use_database_override() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        set_setting(session, "market_open_briefs_enabled", "false")
        set_setting(session, "cn_open_brief_cron", "30 9 * * 1-5")
        set_setting(session, "us_open_brief_cron", "45 10 * * 1-5")

        enabled, cn_cron, us_cron = get_market_open_brief_settings(session)

        assert not enabled
        assert cn_cron == "30 9 * * 1-5"
        assert us_cron == "45 10 * * 1-5"


def test_collection_settings_use_database_override() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        set_setting(session, "collection_enabled", "false")
        set_setting(session, "collect_all_cron", "30 * * * *")

        enabled, cron = get_collection_settings(session)

        assert not enabled
        assert cron == "30 * * * *"


def test_daily_noon_brief_settings_use_database_override() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        set_setting(session, "daily_noon_brief_enabled", "false")
        set_setting(session, "daily_noon_brief_cron", "15 12 * * *")

        enabled, cron = get_daily_noon_brief_settings(session)

        assert not enabled
        assert cron == "15 12 * * *"


def test_workday_time_to_cron() -> None:
    assert workday_time_to_cron("09:30") == "30 9 * * 1-5"
    assert workday_time_to_cron("16:05") == "5 16 * * 1-5"


def test_daily_time_to_cron() -> None:
    assert daily_time_to_cron("12:00") == "0 12 * * *"
    assert daily_time_to_cron("13:20") == "20 13 * * *"


def test_workday_time_to_cron_rejects_invalid_time() -> None:
    with pytest.raises(ValueError):
        workday_time_to_cron("25:00")

    with pytest.raises(ValueError):
        daily_time_to_cron("24:00")


def test_cron_to_workday_time() -> None:
    assert cron_to_workday_time("5 16 * * 1-5") == "16:05"
    assert cron_to_workday_time("*/5 * * * *") == ""


def test_cron_to_daily_time() -> None:
    assert cron_to_daily_time("20 13 * * *") == "13:20"
    assert cron_to_daily_time("5 16 * * 1-5") == ""

