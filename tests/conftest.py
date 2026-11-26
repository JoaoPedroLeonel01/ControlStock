"""Shared pytest configuration.

DATABASE_URL is required by the application settings, and it must be set
before any application module is imported:

* With TEST_DATABASE_URL set, DATABASE_URL is forced to it, so the app and
  Alembic can only ever reach the dedicated test database (never a real one
  exported in the shell or read from .env).
* Without it, a placeholder URL lets the unit tests run with no database
  (integration tests are skipped; in CI a missing TEST_DATABASE_URL aborts).
"""

import os

from tests.db_safety import resolve_test_database_url

_test_database_url = resolve_test_database_url(os.environ)

if _test_database_url:
    os.environ["DATABASE_URL"] = _test_database_url
else:
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://test_user:test_pass@localhost:5432/control_stock_test",
    )
