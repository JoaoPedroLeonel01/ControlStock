"""Application configuration management using pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global application settings and environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = Field(
        ...,
        description=(
            "Database connection URI (required), e.g. "
            "postgresql+psycopg://user:pass@localhost:5432/control_stock"
        ),
    )
    ENVIRONMENT: str = Field(
        default="development",
        description="Deployment environment (development, test, production)",
    )
    APP_NAME: str = Field(
        default="ControlStock API",
        description="Application title",
    )

    @property
    def sqlalchemy_database_url(self) -> str:
        """Ensure compatibility with SQLAlchemy 2.0 and psycopg3 drivers."""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql://") and not url.startswith(
            "postgresql+psycopg://"
        ):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


settings = Settings()
