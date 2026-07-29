from sqlalchemy import create_mock_engine
from sqlmodel import SQLModel

from app import models  # noqa: F401


def test_all_models_compile_for_mysql() -> None:
    statements: list[str] = []
    engine = create_mock_engine(
        "mysql+pymysql://",
        lambda sql, *multiparams, **params: statements.append(str(sql.compile(dialect=engine.dialect))),
    )

    SQLModel.metadata.create_all(engine)

    ddl = "\n".join(statements)
    assert "CREATE TABLE app_user" in ddl
    assert "CREATE TABLE user_secret" in ddl
    assert "CREATE TABLE distributed_job_lock" in ddl
