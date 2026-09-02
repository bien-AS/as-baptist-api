"""Database runtime and live readiness behavior."""

import os

import httpx
import pytest
from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


async def test_ready_succeeds_against_configured_postgres() -> None:
    database_url = os.environ.get("TEST_API_DATABASE_URL")
    if not database_url:
        pytest.skip("live readiness test requires TEST_API_DATABASE_URL")

    application = create_app(
        Settings(
            database_url=database_url,
            migrations_database_url=database_url,
        )
    )
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/ready")
    finally:
        await application.state.database.dispose()

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
