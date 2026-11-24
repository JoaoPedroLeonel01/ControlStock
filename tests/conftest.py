"""Shared pytest configuration.

DATABASE_URL is required by the application settings. Provide a test value
before any application module is imported so the suite runs without a local
.env file (e.g. in CI). An explicitly exported DATABASE_URL takes precedence.
"""

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test_user:test_pass@localhost:5432/control_stock_test",
)
