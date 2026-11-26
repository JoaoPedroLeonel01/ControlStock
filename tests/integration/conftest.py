"""PostgreSQL fixtures for integration tests.

The test database (TEST_DATABASE_URL, name must end in "_test") is created if
missing, its "public" schema is reset and rebuilt with "alembic upgrade head"
once per session, so triggers and constraints are exactly the production ones.
Each test then runs inside a transaction that is always rolled back.
"""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from tests.db_safety import (
    assert_test_database_url,
    maintenance_url,
    resolve_test_database_url,
)
from tests.integration.factories import rolled_back_session


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = resolve_test_database_url(os.environ)
    if url is None:
        pytest.skip("TEST_DATABASE_URL not set (integration tests need PostgreSQL)")
    assert_test_database_url(url)
    return url


def _create_database_if_missing(url: str) -> None:
    name = make_url(url).database
    admin = create_engine(maintenance_url(url), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def migrated_engine(test_db_url: str) -> Iterator[Engine]:
    _create_database_if_missing(test_db_url)
    engine = create_engine(test_db_url)
    with engine.begin() as conn:
        # Belt and braces: check the database we are really connected to.
        current = conn.execute(text("SELECT current_database()")).scalar_one()
        assert_test_database_url(make_url(test_db_url).set(database=current))
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    # migrations/env.py reads DATABASE_URL, which tests/conftest.py forced to
    # TEST_DATABASE_URL; re-check before running any DDL through Alembic.
    from src.control_stock.core.config import settings

    assert_test_database_url(settings.sqlalchemy_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    with rolled_back_session(migrated_engine) as session:
        yield session


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """API client whose requests share the test's rolled-back session."""
    from src.control_stock.core.database import get_db
    from src.control_stock.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
