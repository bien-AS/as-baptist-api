"""Configuration validation behavior."""

import pytest
from app.config import AppEnvironment, AuthMode, Settings


def test_local_settings_do_not_require_cloud_credentials() -> None:
    settings = Settings()

    assert settings.app_env is AppEnvironment.local
    assert settings.auth_mode is AuthMode.mock


def test_cors_origins_accept_comma_separated_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, https://app.example.test")

    settings = Settings()

    assert settings.cors_origins == (
        "http://localhost:5173",
        "https://app.example.test",
    )


def test_production_settings_fail_before_first_request() -> None:
    with pytest.raises(ValueError, match="Missing required deployed configuration"):
        Settings(app_env=AppEnvironment.production)


def test_blank_production_database_settings_are_rejected() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(
            app_env=AppEnvironment.production,
            database_url="",
            migrations_database_url="",
            auth_mode=AuthMode.supabase,
            supabase_jwks_url="https://auth.example.test/jwks.json",
            supabase_jwt_audience="baptist",
            supabase_jwt_issuer="https://auth.example.test",
        )
