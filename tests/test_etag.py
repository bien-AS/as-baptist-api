"""Tests for tenant-scoped ETags and conditional GET (BE-09)."""

import os
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from app.config import Settings
from app.core.etag import compute_etag
from app.db.rls import RequestContext
from app.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

MOCK_TOKEN = "dev-token"
TENANT_A = UUID("00000000-0000-0000-0000-00000000000f")
TENANT_B = UUID("00000000-0000-0000-0000-000000000010")
USER_A = UUID("00000000-0000-0000-0000-00000000001f")
USER_B = UUID("00000000-0000-0000-0000-000000000020")


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {MOCK_TOKEN}"}


def test_compute_etag_differs_across_tenants_for_identical_content() -> None:
    """The core BE-09 requirement: same body, different tenant, different ETag."""

    ctx_a = RequestContext(tenant_id=TENANT_A, actor_id=USER_A, role="as_admin")
    ctx_b = RequestContext(tenant_id=TENANT_B, actor_id=USER_B, role="as_admin")

    assert compute_etag(ctx_a, "identical-body") != compute_etag(ctx_b, "identical-body")


def test_compute_etag_is_stable_for_same_tenant_and_content() -> None:
    ctx = RequestContext(tenant_id=TENANT_A, actor_id=USER_A, role="as_admin")

    assert compute_etag(ctx, "same-body") == compute_etag(ctx, "same-body")


@pytest_asyncio.fixture
async def two_tenant_clients() -> AsyncIterator[tuple[httpx.AsyncClient, httpx.AsyncClient]]:
    """Two tenants, each with one identically-slugged, identically-named location."""

    migrator_url = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
    if not migrator_url:
        pytest.skip("etag integration tests require TEST_MIGRATIONS_DATABASE_URL")
    engine = create_async_engine(migrator_url, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.execute(text("truncate tenant cascade"))
        for tenant_id, user_id, slug_suffix in ((TENANT_A, USER_A, "a"), (TENANT_B, USER_B, "b")):
            await connection.execute(
                text(
                    "insert into tenant (id, slug, name, tier, status) values "
                    "(:tenant_id, :slug, 'Etag Tests', 'agency_client', 'active')"
                ),
                {"tenant_id": tenant_id, "slug": f"etag-tests-{slug_suffix}"},
            )
            await connection.execute(
                text(
                    "insert into user_profile (id, email, full_name) values "
                    "(:id, :email, 'Etag Tester') on conflict (id) do nothing"
                ),
                {"id": user_id, "email": f"etag-{slug_suffix}@example.test"},
            )
            await connection.execute(
                text(
                    "insert into location (tenant_id, slug, name, listing_type, "
                    "facility_type, address, city, state, zip, source) values "
                    "(:tenant_id, 'shared-slug', 'Shared Facility', 'facility', "
                    "'hospital', '1 Shared Way', 'Memphis', 'TN', '38103', 'computed')"
                ),
                {"tenant_id": tenant_id},
            )

    def client_for(tenant_id: UUID, user_id: UUID) -> httpx.AsyncClient:
        settings = Settings(mock_auth_tenant_id=tenant_id, mock_auth_user_id=user_id)
        application = create_app(settings)
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    client_a = client_for(TENANT_A, USER_A)
    client_b = client_for(TENANT_B, USER_B)
    yield client_a, client_b
    await client_a.aclose()
    await client_b.aclose()
    await engine.dispose()


async def test_identical_content_in_two_tenants_produces_different_etags(
    two_tenant_clients: tuple[httpx.AsyncClient, httpx.AsyncClient],
) -> None:
    client_a, client_b = two_tenant_clients

    response_a = await client_a.get("/v1/locations/shared-slug", headers=auth())
    response_b = await client_b.get("/v1/locations/shared-slug", headers=auth())

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert response_a.json()["data"]["name"] == response_b.json()["data"]["name"]
    assert response_a.headers["ETag"] != response_b.headers["ETag"]


async def test_repeat_request_with_if_none_match_returns_304(
    two_tenant_clients: tuple[httpx.AsyncClient, httpx.AsyncClient],
) -> None:
    client_a, _ = two_tenant_clients

    first = await client_a.get("/v1/locations/shared-slug", headers=auth())
    etag = first.headers["ETag"]

    second = await client_a.get(
        "/v1/locations/shared-slug",
        headers={**auth(), "If-None-Match": etag},
    )

    assert second.status_code == 304
    assert second.content == b""


async def test_me_repeat_request_with_if_none_match_returns_304(
    two_tenant_clients: tuple[httpx.AsyncClient, httpx.AsyncClient],
) -> None:
    client_a, _ = two_tenant_clients

    first = await client_a.get("/v1/me", headers=auth())
    etag = first.headers["ETag"]

    second = await client_a.get("/v1/me", headers={**auth(), "If-None-Match": etag})

    assert second.status_code == 304


async def test_list_locations_etag_differs_across_tenants(
    two_tenant_clients: tuple[httpx.AsyncClient, httpx.AsyncClient],
) -> None:
    client_a, client_b = two_tenant_clients

    response_a = await client_a.get("/v1/locations", headers=auth())
    response_b = await client_b.get("/v1/locations", headers=auth())

    assert response_a.headers["ETag"] != response_b.headers["ETag"]
