"""Application configuration loaded from environment variables."""

from enum import StrEnum
from functools import lru_cache
from typing import Self
from uuid import UUID

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_DATABASE_URL = "postgresql+asyncpg://app_api:change-me@localhost:5432/baptist"
LOCAL_MIGRATIONS_DATABASE_URL = (
    "postgresql+asyncpg://app_migrator:change-me@localhost:5432/baptist"
)


class AppEnvironment(StrEnum):
    """Deployment environments with different configuration requirements."""

    local = "local"
    test = "test"
    staging = "staging"
    production = "production"


class AuthMode(StrEnum):
    """Authentication source used by the API."""

    mock = "mock"
    supabase = "supabase"


class Settings(BaseSettings):
    """Typed runtime settings.

    Local and test environments have safe development defaults. Staging and
    production reject those defaults and require the real database and JWT
    verification settings during application construction.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: AppEnvironment = AppEnvironment.local
    app_name: str = "baptist-api"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = LOCAL_DATABASE_URL
    migrations_database_url: str = LOCAL_MIGRATIONS_DATABASE_URL
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    auth_mode: AuthMode = AuthMode.mock
    supabase_jwks_url: str | None = None
    supabase_jwt_audience: str | None = None
    supabase_jwt_issuer: str | None = None
    mock_auth_token: str = "dev-token"
    mock_auth_user_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    mock_auth_tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000002")
    mock_auth_role: str = "as_admin"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> tuple[str, ...]:
        """Accept comma-separated `.env` values as well as test sequences."""

        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
        if isinstance(value, (list, tuple, set)):
            return tuple(str(origin).strip() for origin in value if str(origin).strip())
        raise TypeError("CORS_ORIGINS must be a comma-separated string or sequence")

    @model_validator(mode="after")
    def validate_deployed_environment(self) -> Self:
        """Reject local placeholders and mock auth outside local/test runs."""

        if self.app_env not in {AppEnvironment.staging, AppEnvironment.production}:
            return self

        missing: list[str] = []
        if self.database_url == LOCAL_DATABASE_URL:
            missing.append("DATABASE_URL")
        if self.migrations_database_url == LOCAL_MIGRATIONS_DATABASE_URL:
            missing.append("MIGRATIONS_DATABASE_URL")
        if self.auth_mode is AuthMode.mock:
            missing.append("AUTH_MODE=supabase")
        if not self.supabase_jwks_url:
            missing.append("SUPABASE_JWKS_URL")
        if not self.supabase_jwt_audience:
            missing.append("SUPABASE_JWT_AUDIENCE")
        if not self.supabase_jwt_issuer:
            missing.append("SUPABASE_JWT_ISSUER")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required deployed configuration: {joined}")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable configuration snapshot."""

    return Settings()
