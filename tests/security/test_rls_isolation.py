"""Cross-tenant isolation tests committed before policy enforcement."""

import asyncio
from uuid import UUID

import pytest
from app.db.rls import RequestContext, tenant_context
from app.models import Base, Membership, UserProfile
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.security.conftest import Seed

pytestmark = pytest.mark.integration

LOCATION_ALPHA = UUID("00000000-0000-0000-0000-00000000003a")
LOCATION_BETA = UUID("00000000-0000-0000-0000-00000000003b")
CAN_READ_LOCATION_SQL = text("select app.can_read_location(:loc)")


def context_for(seed: Seed, tenant: str = "a") -> RequestContext:
    if tenant == "a":
        return RequestContext(seed.tenant_a, seed.user_a, "as_admin")
    return RequestContext(seed.tenant_b, seed.user_b, "as_admin")


async def test_unbound_tenant_returns_zero_rows(db: AsyncSession, seed: Seed) -> None:
    async with db.begin():
        rows = (await db.scalars(select(Membership))).all()

    assert rows == []


async def test_cross_tenant_select_returns_only_bound_tenant(
    db: AsyncSession,
    seed: Seed,
) -> None:
    async with tenant_context(db, context_for(seed)):
        rows = (await db.scalars(select(Membership))).all()

    assert {row.tenant_id for row in rows} == {seed.tenant_a}


async def test_cross_tenant_insert_is_blocked(db: AsyncSession, seed: Seed) -> None:
    with pytest.raises(DBAPIError, match="cross-tenant insert blocked"):
        async with tenant_context(db, context_for(seed)):
            await db.execute(
                insert(Membership).values(
                    tenant_id=seed.tenant_b,
                    user_id=seed.user_a,
                    role="client_user",
                    status="active",
                )
            )


async def test_update_cannot_move_a_row_between_tenants(
    db: AsyncSession,
    seed: Seed,
) -> None:
    with pytest.raises(DBAPIError):
        async with tenant_context(db, context_for(seed)):
            await db.execute(
                update(Membership)
                .where(Membership.id == seed.membership_a)
                .values(tenant_id=seed.tenant_b)
            )


async def test_context_settings_disappear_after_commit(db: AsyncSession, seed: Seed) -> None:
    async with tenant_context(db, context_for(seed)):
        row = (
            await db.execute(
                text(
                    "select app.current_tenant_id(), app.current_actor_id(), "
                    "app.current_role()"
                )
            )
        ).one()
        assert row[0] == seed.tenant_a
        assert row[1] == seed.user_a
        assert row[2] == "as_admin"

    async with db.begin():
        row = (
            await db.execute(
                text(
                    "select current_setting('app.tenant_id', true), "
                    "current_setting('app.actor_id', true), "
                    "current_setting('app.role', true)"
                )
            )
        ).one()
    # PostgreSQL restores an unset custom GUC as an empty string on the same
    # connection after SET LOCAL commits. The app.current_* functions use
    # nullif/coalesce, so this is still an unbound context.
    assert row == ("", "", "")


async def test_concurrent_sessions_keep_contexts_isolated(
    api_engine: AsyncEngine,
    seed: Seed,
) -> None:
    factory = async_sessionmaker(api_engine, expire_on_commit=False, autoflush=False)

    async def read_context(ctx: RequestContext) -> tuple[object, set[object]]:
        async with factory() as session:
            async with tenant_context(session, ctx):
                await asyncio.sleep(0.02)
                current = (
                    await session.execute(text("select app.current_tenant_id()"))
                ).scalar_one()
                tenants = {
                    row.tenant_id for row in (await session.scalars(select(Membership))).all()
                }
                return current, tenants

    result_a, result_b = await asyncio.gather(
        read_context(context_for(seed, "a")),
        read_context(context_for(seed, "b")),
    )

    assert result_a == (seed.tenant_a, {seed.tenant_a})
    assert result_b == (seed.tenant_b, {seed.tenant_b})


@pytest.mark.parametrize(
    "table_name",
    tuple(table.name for table in Base.metadata.tables.values()),
)
async def test_every_tenant_spine_table_has_rls_forced(
    db: AsyncSession,
    seed: Seed,
    table_name: str,
) -> None:
    async with db.begin():
        enabled, forced = (
            await db.execute(
                text(
                    "select relrowsecurity, relforcerowsecurity "
                    "from pg_class where relname = :table_name"
                ),
                {"table_name": table_name},
            )
        ).one()

    assert enabled and forced, f"{table_name} is missing RLS enable/force"


async def test_operator_can_read_any_location(db: AsyncSession, seed: Seed) -> None:
    """`app.is_operator()` short-circuits location scoping regardless of assignment rows."""

    async with tenant_context(db, context_for(seed)):
        result = await db.execute(CAN_READ_LOCATION_SQL, {"loc": LOCATION_ALPHA})

    assert result.scalar_one() is True


async def test_unrestricted_member_can_read_any_location(db: AsyncSession, seed: Seed) -> None:
    """No `membership_location` rows means "all locations in the tenant"."""

    ctx = RequestContext(seed.tenant_a, seed.user_a, "client_user")
    async with tenant_context(db, ctx):
        result = await db.execute(CAN_READ_LOCATION_SQL, {"loc": LOCATION_ALPHA})

    assert result.scalar_one() is True


async def test_scoped_member_sees_only_assigned_location(
    db: AsyncSession,
    seed: Seed,
    migrator_engine: AsyncEngine,
) -> None:
    """A `client_user` restricted to one location cannot read another."""

    async with migrator_engine.begin() as connection:
        await connection.execute(
            text(
                "insert into membership_location (membership_id, location_id) "
                "values (:membership_id, :location_id)"
            ),
            {"membership_id": seed.membership_a, "location_id": LOCATION_ALPHA},
        )

    ctx = RequestContext(seed.tenant_a, seed.user_a, "client_user")
    async with tenant_context(db, ctx):
        allowed = await db.execute(CAN_READ_LOCATION_SQL, {"loc": LOCATION_ALPHA})
        denied = await db.execute(CAN_READ_LOCATION_SQL, {"loc": LOCATION_BETA})

    assert allowed.scalar_one() is True
    assert denied.scalar_one() is False


async def test_worker_cannot_read_identity_surface(
    worker_db: AsyncSession,
    seed: Seed,
) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_context(worker_db, context_for(seed)):
            await worker_db.scalars(select(UserProfile))


async def test_app_api_cannot_create_tables(db: AsyncSession, seed: Seed) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_context(db, context_for(seed)):
            await db.execute(text("create table public.rls_ddl_probe (id integer)"))
