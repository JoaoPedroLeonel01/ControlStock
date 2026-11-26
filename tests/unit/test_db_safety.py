import pytest
from sqlalchemy.engine import make_url

from tests.db_safety import (
    assert_test_database_url,
    maintenance_url,
    resolve_test_database_url,
)

TEST_URL = "postgresql+psycopg://u:s3cret@localhost:5442/control_stock_test"


def test_guard_accepts_test_suffix() -> None:
    assert assert_test_database_url(TEST_URL) is None


@pytest.mark.parametrize(
    "name", ["control_stock", "control_stock_sandbox", "neondb", "postgres"]
)
def test_guard_rejects_real_databases(name: str) -> None:
    with pytest.raises(ValueError, match=name):
        assert_test_database_url(f"postgresql+psycopg://u:p@localhost:5442/{name}")


def test_resolve_returns_none_locally() -> None:
    assert resolve_test_database_url({}) is None


def test_resolve_requires_url_in_ci() -> None:
    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL"):
        resolve_test_database_url({"CI": "true"})


def test_resolve_strips_whitespace() -> None:
    assert resolve_test_database_url({"TEST_DATABASE_URL": " x_test \n"}) == "x_test"


def test_maintenance_url_targets_postgres_db() -> None:
    url = make_url(maintenance_url(TEST_URL))
    assert url.database == "postgres"
    assert url.password == "s3cret"
    assert url.port == 5442


@pytest.mark.parametrize("key", ["dbname", "service", "host"])
def test_guard_rejects_connection_overrides_in_query(key: str) -> None:
    # psycopg lets query parameters override the database in the URL path.
    with pytest.raises(ValueError, match=key):
        assert_test_database_url(f"{TEST_URL}?{key}=control_stock")
