import pytest
from sqlalchemy.orm import Session

from src.control_stock.core.config import Settings, settings
from src.control_stock.core.database import NAMING_CONVENTION, Base, get_db


def test_settings_loaded() -> None:
    assert settings.APP_NAME == "ControlStock API"
    assert settings.sqlalchemy_database_url.startswith("postgresql+psycopg://")


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        (
            "postgresql+psycopg://u:p@h:5432/db",
            "postgresql+psycopg://u:p@h:5432/db",
        ),
        # Neon connection string: the query string (TLS options) must survive.
        (
            "postgresql://u:p@ep-x-123.us-east-2.aws.neon.tech/neondb"
            "?sslmode=require&channel_binding=require",
            "postgresql+psycopg://u:p@ep-x-123.us-east-2.aws.neon.tech/neondb"
            "?sslmode=require&channel_binding=require",
        ),
    ],
)
def test_sqlalchemy_database_url_normalizes_driver(raw_url: str, expected: str) -> None:
    assert Settings(DATABASE_URL=raw_url).sqlalchemy_database_url == expected


def test_base_metadata_uses_naming_convention() -> None:
    for key, template in NAMING_CONVENTION.items():
        assert Base.metadata.naming_convention[key] == template


def test_get_db_yields_session_and_closes() -> None:
    db_gen = get_db()
    db = next(db_gen)
    assert isinstance(db, Session)
    with pytest.raises(StopIteration):
        next(db_gen)
