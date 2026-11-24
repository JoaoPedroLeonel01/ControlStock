"""SQLAlchemy 2.0 database engine, session factory, and declarative base."""

from collections.abc import Generator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.control_stock.core.config import settings

# Engine manages database connection pooling
connect_args = (
    {"check_same_thread": False}
    if settings.sqlalchemy_database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.sqlalchemy_database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)

# Session factory for creating transaction-scoped sessions
# expire_on_commit=False keeps loaded attributes usable after commit (e.g. when
# serializing the response), avoiding implicit lazy reloads.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


# Deterministic constraint names keep Alembic migrations (and downgrades)
# reproducible across environments instead of relying on DB-generated names.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
