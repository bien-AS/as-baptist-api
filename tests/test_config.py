"""Configuration validation behavior."""

import pytest
from app.config import AppEnvironment, AuthMode, Settings


def test_local_settings_do_not_require_cloud_credentials() -> None:
    settings = Settings()

    assert settings.app_env is AppEnvironment.local
    assert settings.auth_mode is AuthMode.mock


def test_production_settings_fail_before_first_request() -> None:
    with pytest.raises(ValueError, match="Missing required deployed configuration"):
        Settings(app_env=AppEnvironment.production)
