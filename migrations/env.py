from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.control_stock.core.config import settings
from src.control_stock.core.database import Base

# NOTE: models must be imported so autogenerate can detect their tables.
# Once they exist, add to the import block above (ruff keeps it sorted):
#     from src.control_stock import models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for 'autogenerate' support
target_metadata = Base.metadata

# Inject the database URL from application settings (single source of truth).
# ConfigParser treats "%" as interpolation syntax, so it must be escaped to
# support URL-encoded credentials (e.g. a password like "p%40ss").
config.set_main_option(
    "sqlalchemy.url", settings.sqlalchemy_database_url.replace("%", "%%")
)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB connection)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (against a live DB connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
