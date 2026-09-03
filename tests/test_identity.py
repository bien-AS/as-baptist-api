"""Tests for `GET /v1/me` and the tenant-context dependency (BE-08)."""

import os
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from app.config import Settings
from app.core.errors import ApiProblem
from app.core.security import AuthenticatedUser
from app.deps import get_tenant_context
from app.main import create_app
from app.schemas import ProblemCode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

MOCK_TOKEN = "dev-token"
TENANT_ID = UUID("00000000-0000-0000-0000-00000000000e")
USER_ID = UUID("00000000-0000-0000-0000-00000000001e")


def auth(token: str = MOCK_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_get_tenant_context_raises_when_tenant_claim_missing() -> None:
    user = AuthenticatedUser(id=USER_ID, tenant_id=None, role="client_user")

    with pytest.raises(ApiProblem) as excinfo:
        get_tenant_context(user)

    assert excinfo.value.code is ProblemCode.TENANT_SCOPE_MISSING


@pytest_asyncio.fixture
async def seeded_client(request: pytest.FixtureRequest) -> AsyncIterator[httpx.AsyncClient]:
    status: str = getattr(request, "param", "active")
    migrator_url = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
    if not migrator_url:
        pytest.skip("identity integration tests require TEST_MIGRATIONS_DATABASE_URL")
    engine = create_async_engine(migrator_url, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.execute(text("truncate tenant cascade"))
        await connection.execute(
            text(
                "insert into tenant (id, slug, name, tier, status) values "
                "(:tenant_id, 'identity-tests', 'Identity Tests', 'baptist', 'active')"
            ),
            {"tenant_id": TENANT_ID},
        )
        await connection.execute(
            text(
                "insert into user_profile (id, email, full_name) values "
                "(:id, 'me-tester@example.test', 'Me Tester') "
                "on conflict (id) do nothing"
            ),
            {"id": USER_ID},
        )
        await connection.execute(
            text(
                "insert into membership (tenant_id, user_id, role, status) values "
                "(:tenant_id, :user_id, 'as_admin', :status)"
            ),
            {"tenant_id": TENANT_ID, "user_id": USER_ID, "status": status},
        )

    settings = Settings(mock_auth_tenant_id=TENANT_ID, mock_auth_user_id=USER_ID)
    application = create_app(settings)
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await engine.dispose()


async def test_me_requires_authentication() -> None:
    application = create_app(Settings())
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/me")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_me_returns_seeded_identity(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get("/v1/me", headers=auth())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"]["id"] == str(USER_ID)
    assert data["tenant"]["id"] == str(TENANT_ID)
    assert data["tenant"]["slug"] == "identity-tests"
    assert data["role"] == "as_admin"
    assert data["must_accept_invite"] is False


@pytest.mark.parametrize("seeded_client", ["pending"], indirect=True)
async def test_me_reports_pending_invite(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.get("/v1/me", headers=auth())

    assert response.status_code == 200
    assert response.json()["data"]["must_accept_invite"] is True
