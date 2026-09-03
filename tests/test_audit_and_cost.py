"""Integration tests for audit.write_card() and cost.assert_budget() (BE-06)."""

import os
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio
from app.db.rls import RequestContext, tenant_context
from app.services.audit import write_card
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

pytestmark = pytest.mark.integration

TENANT_ID = UUID("00000000-0000-0000-0000-00000000000c")
USER_ID = UUID("00000000-0000-0000-0000-00000000001c")

BUDGET_INSERT_SQL = text(
    "insert into cost_budget (tenant_id, period_month, monthly_cap_usd, "
    "per_run_cap_usd, balance_floor_usd, hard_stop) values "
    "(:tenant_id, date_trunc('month', current_date)::date, "
    ":monthly_cap, :per_run_cap, :balance_floor, true)"
)


def ctx(role: str = "as_admin") -> RequestContext:
    return RequestContext(tenant_id=TENANT_ID, actor_id=USER_ID, role=role)


@pytest.fixture(scope="session")
def database_urls() -> tuple[str, str]:
    api_url = os.environ.get("TEST_API_DATABASE_URL")
    migrator_url = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
    if not api_url or not migrator_url:
        pytest.skip(
            "audit/cost integration tests require TEST_API_DATABASE_URL and "
            "TEST_MIGRATIONS_DATABASE_URL"
        )
    return api_url, migrator_url


@pytest_asyncio.fixture(scope="session")
async def api_engine(database_urls: tuple[str, str]) -> AsyncIterator[AsyncEngine]:
    api_url, _ = database_urls
    engine = create_async_engine(api_url, pool_size=4, max_overflow=0, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def migrator_engine(database_urls: tuple[str, str]) -> AsyncIterator[AsyncEngine]:
    _, migrator_url = database_urls
    engine = create_async_engine(migrator_url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(api_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(api_engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def seed(migrator_engine: AsyncEngine) -> AsyncIterator[None]:
    """A dedicated tenant, self-contained regardless of other files' fixtures.

    `tenant` truncation cascades to `location`, `audit_card`, `cost_ledger`,
    and `cost_budget` automatically (all FK to `tenant`), matching the
    established pattern in `tests/security/conftest.py`. `user_profile` is a
    global table with no FK to `tenant` (`03` §16), so it survives the
    cascade — the insert below is idempotent instead.
    """

    async with migrator_engine.begin() as connection:
        await connection.execute(text("truncate tenant cascade"))
        await connection.execute(
            text(
                "insert into tenant (id, slug, name, tier, status) values "
                "(:tenant_id, 'audit-cost-tests', 'Audit Cost Tests', "
                " 'agency_client', 'active')"
            ),
            {"tenant_id": TENANT_ID},
        )
        await connection.execute(
            text(
                "insert into user_profile (id, email, full_name) values "
                "(:id, 'audit-tester@example.test', 'Audit Tester') "
                "on conflict (id) do nothing"
            ),
            {"id": USER_ID},
        )
    yield


async def test_write_card_requires_bound_tenant(db: AsyncSession, seed: None) -> None:
    async with db.begin():
        with pytest.raises(DBAPIError, match="no tenant bound"):
            await write_card(
                db, location_id=None, verb="create", action="x", resource_type="y"
            )


async def test_write_card_resolves_actor_from_session(db: AsyncSession, seed: None) -> None:
    async with tenant_context(db, ctx()):
        card_id = await write_card(
            db,
            location_id=None,
            verb="create",
            action="Queued a thing",
            resource_type="widget",
        )
        row = (
            await db.execute(
                text(
                    "select actor_label, actor_role, action from audit_card where id = :id"
                ),
                {"id": card_id},
            )
        ).one()

    assert row.actor_label == "Audit Tester"
    assert row.actor_role == "as_admin"
    assert row.action == "Queued a thing"


async def test_audit_card_update_denied_for_app_api(db: AsyncSession, seed: None) -> None:
    async with tenant_context(db, ctx()):
        card_id = await write_card(
            db, location_id=None, verb="create", action="x", resource_type="y"
        )
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(
                text("update audit_card set action = 'tampered' where id = :id"),
                {"id": card_id},
            )


async def test_audit_card_delete_denied_for_app_api(db: AsyncSession, seed: None) -> None:
    async with tenant_context(db, ctx()):
        card_id = await write_card(
            db, location_id=None, verb="create", action="x", resource_type="y"
        )
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(text("delete from audit_card where id = :id"), {"id": card_id})


async def test_audit_card_immutable_trigger_blocks_privileged_role(
    migrator_engine: AsyncEngine,
    seed: None,
) -> None:
    """`app_migrator` holds the UPDATE grant but the append-only trigger still fires."""

    factory = async_sessionmaker(migrator_engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        async with tenant_context(session, ctx()):
            card_id = await write_card(
                session, location_id=None, verb="create", action="x", resource_type="y"
            )
        async with session.begin():
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    text("update audit_card set action = 'tampered' where id = :id"),
                    {"id": card_id},
                )


async def test_assert_budget_raises_over_per_run_cap(db: AsyncSession, seed: None) -> None:
    async with tenant_context(db, ctx()):
        await db.execute(
            BUDGET_INSERT_SQL,
            {
                "tenant_id": TENANT_ID,
                "monthly_cap": 500.00,
                "per_run_cap": 20.00,
                "balance_floor": 100.00,
            },
        )
        with pytest.raises(DBAPIError, match="exceeds per-run cap"):
            await db.execute(text("select cost.assert_budget(25.00, null)"))


async def test_assert_budget_raises_over_monthly_cap(db: AsyncSession, seed: None) -> None:
    async with tenant_context(db, ctx()):
        await db.execute(
            BUDGET_INSERT_SQL,
            {
                "tenant_id": TENANT_ID,
                "monthly_cap": 10.00,
                "per_run_cap": 20.00,
                "balance_floor": 0.00,
            },
        )
        await db.execute(
            text(
                "insert into cost_ledger (tenant_id, provider, operation, unit, units, "
                "unit_cost_usd, cost_usd, billing, scope, source) values "
                "(:tenant_id, 'dataforseo', 'grid_scan', 'per pin', 1000, "
                "0.008, 8.0000, 'billed', 'top5', 'computed')"
            ),
            {"tenant_id": TENANT_ID},
        )
        with pytest.raises(DBAPIError, match="monthly cap exceeded"):
            await db.execute(text("select cost.assert_budget(5.00, null)"))


async def test_assert_budget_raises_below_balance_floor(db: AsyncSession, seed: None) -> None:
    async with tenant_context(db, ctx()):
        await db.execute(
            BUDGET_INSERT_SQL,
            {
                "tenant_id": TENANT_ID,
                "monthly_cap": 500.00,
                "per_run_cap": 50.00,
                "balance_floor": 100.00,
            },
        )
        with pytest.raises(DBAPIError, match="would fall below floor"):
            await db.execute(text("select cost.assert_budget(5.00, 103.00)"))


async def test_cost_ledger_math_check_rejects_mismatched_row(
    db: AsyncSession, seed: None
) -> None:
    async with tenant_context(db, ctx()):
        with pytest.raises(DBAPIError, match="cost_ledger_math"):
            await db.execute(
                text(
                    "insert into cost_ledger (tenant_id, provider, operation, unit, units, "
                    "unit_cost_usd, cost_usd, billing, scope, source) values "
                    "(:tenant_id, 'dataforseo', 'grid_scan', 'per pin', 10, "
                    "0.01, 999.00, 'billed', 'top5', 'computed')"
                ),
                {"tenant_id": TENANT_ID},
            )
