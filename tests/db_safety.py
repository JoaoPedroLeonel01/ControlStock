"""Guards that keep the test suite away from real databases.

Integration tests build their schema by dropping and recreating ``public``, so
they must only ever run against a dedicated database whose name ends in
``_test`` (never ``control_stock``, the sandbox or production).
"""

from collections.abc import Mapping

from sqlalchemy.engine import make_url

TEST_DB_SUFFIX = "_test"

# libpq/psycopg let these query parameters override the host or database given
# in the URL path, which would bypass the name check below.
CONNECTION_OVERRIDES = ("dbname", "service", "host")


def resolve_test_database_url(env: Mapping[str, str]) -> str | None:
    """Return TEST_DATABASE_URL from ``env``, or None when it is not set.

    In CI (``CI`` set) a missing URL is an error: integration tests must run
    there, never be skipped silently.
    """
    url = (env.get("TEST_DATABASE_URL") or "").strip()
    if url:
        return url
    if env.get("CI"):
        raise RuntimeError("TEST_DATABASE_URL is required in CI")
    return None


def assert_test_database_url(url: str) -> None:
    """Raise ValueError unless the URL points to a database named '*_test'."""
    parsed = make_url(url)
    overrides = sorted(set(parsed.query) & set(CONNECTION_OVERRIDES))
    if overrides:
        raise ValueError(
            f"Refusing TEST_DATABASE_URL with connection overrides {overrides}: "
            "set the database name in the URL path only"
        )
    name = parsed.database or ""
    if not name.endswith(TEST_DB_SUFFIX):
        raise ValueError(
            f"Refusing to use database {name!r}: the test database name must "
            f"end with {TEST_DB_SUFFIX!r}"
        )


def maintenance_url(url: str) -> str:
    """Same server and credentials, connected to the 'postgres' database."""
    return make_url(url).set(database="postgres").render_as_string(hide_password=False)
