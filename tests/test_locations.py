"""Integration tests for the Location domain — real Postgres, real HTTP."""

import os
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from app.config import Settings
from app.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

MOCK_TOKEN = "dev-token"
TENANT_ID = "00000000-0000-0000-0000-000000000002"


def auth(token: str = MOCK_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def clean_locations() -> AsyncIterator[None]:
    """Reset location tables and re-assert the mock-auth tenant before each test.

    Self-contained on purpose: `tests/security/test_rls_isolation.py`'s `seed`
    fixture truncates `tenant` with CASCADE, which also empties `location`
    (and the seeded local-dev tenant row) whenever it runs earlier in the same
    session. Depending on `sql/seed/local.sql` having been applied out-of-band
    would make this file's pass/fail depend on test collection order.
    """

    migrator_url = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
    if not migrator_url:
        pytest.skip("location integration tests require TEST_MIGRATIONS_DATABASE_URL")
    engine = create_async_engine(migrator_url, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.execute(text("truncate location_alias, location cascade"))
        await connection.execute(
            text(
                "insert into tenant (id, slug, name, tier, status) values "
                "(:tenant_id, 'baptist-local', 'Baptist Local Workspace', "
                " 'baptist', 'active') "
                "on conflict (id) do nothing"
            ),
            {"tenant_id": TENANT_ID},
        )
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def operator_client(clean_locations: None) -> AsyncIterator[httpx.AsyncClient]:
    application = create_app(Settings(mock_auth_role="as_admin"))
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest_asyncio.fixture
async def viewer_client(clean_locations: None) -> AsyncIterator[httpx.AsyncClient]:
    application = create_app(Settings(mock_auth_role="client_user"))
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


def location_payload(slug: str) -> dict[str, object]:
    return {
        "slug": slug,
        "name": "Test Facility",
        "listing_type": "facility",
        "facility_type": "hospital",
        "address": "1 Test Way",
        "city": "Memphis",
        "state": "TN",
        "zip": "38103",
        "source": "computed",
    }


async def test_list_locations_requires_authentication(operator_client: httpx.AsyncClient) -> None:
    response = await operator_client.get("/v1/locations")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_list_locations_returns_empty_paginated_envelope(
    operator_client: httpx.AsyncClient,
) -> None:
    response = await operator_client.get("/v1/locations", headers=auth())

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["page"] == {"limit": 50, "offset": 0, "total": 0, "has_more": False}
    assert body["meta"]["scope"]["tenant"] == TENANT_ID


async def test_get_location_missing_slug_returns_404(operator_client: httpx.AsyncClient) -> None:
    response = await operator_client.get("/v1/locations/does-not-exist", headers=auth())

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_create_then_read_location_round_trips(
    operator_client: httpx.AsyncClient,
) -> None:
    create_response = await operator_client.post(
        "/v1/locations", headers=auth(), json=location_payload("bmh-memphis")
    )
    assert create_response.status_code == 201
    created = create_response.json()["data"]
    assert created["slug"] == "bmh-memphis"
    assert created["status"] == "active"

    get_response = await operator_client.get("/v1/locations/bmh-memphis", headers=auth())
    assert get_response.status_code == 200
    assert get_response.json()["data"]["name"] == "Test Facility"

    list_response = await operator_client.get("/v1/locations", headers=auth())
    assert list_response.json()["page"]["total"] == 1


async def test_update_location_applies_partial_changes(
    operator_client: httpx.AsyncClient,
) -> None:
    await operator_client.post(
        "/v1/locations", headers=auth(), json=location_payload("bmh-anderson")
    )

    response = await operator_client.patch(
        "/v1/locations/bmh-anderson",
        headers=auth(),
        json={"display_name": "BMH - Anderson"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["display_name"] == "BMH - Anderson"


async def test_create_location_rejects_non_operator(viewer_client: httpx.AsyncClient) -> None:
    response = await viewer_client.post(
        "/v1/locations", headers=auth(), json=location_payload("blocked")
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ROLE"


async def test_cross_tenant_lookup_returns_404_not_403(
    operator_client: httpx.AsyncClient,
) -> None:
    """A location in another tenant must be indistinguishable from a typo (`05` §3)."""

    migrator_url = os.environ["TEST_MIGRATIONS_DATABASE_URL"]
    engine = create_async_engine(migrator_url, pool_pre_ping=True)
    other_tenant_id = "00000000-0000-0000-0000-0000000000aa"
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "insert into tenant (id, slug, name, tier, status) values "
                "(:id, 'other-tenant', 'Other Tenant', 'agency_client', 'active') "
                "on conflict (id) do nothing"
            ),
            {"id": other_tenant_id},
        )
        await connection.execute(
            text(
                "insert into location "
                "(tenant_id, slug, name, listing_type, facility_type, "
                " address, city, state, zip, source) values "
                "(:tenant_id, 'other-tenant-location', 'Other', 'facility', 'hospital', "
                " '1 Other Way', 'Memphis', 'TN', '38103', 'computed')"
            ),
            {"tenant_id": other_tenant_id},
        )
    await engine.dispose()

    response = await operator_client.get(
        "/v1/locations/other-tenant-location", headers=auth()
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
