"""Integration tests for the approval ladder primitive (BE-07)."""

import asyncio
import os
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.core.errors import ApiProblem
from app.core.idempotency import require_idempotency_key
from app.db.rls import RequestContext, tenant_context
from app.schemas import ProblemCode
from app.services import approval_ladder
from app.services.approval_ladder import CostUnit
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

pytestmark = pytest.mark.integration

TENANT_ID = UUID("00000000-0000-0000-0000-00000000000d")
USER_ID = UUID("00000000-0000-0000-0000-00000000001d")

BUDGET_INSERT_SQL = text(
    "insert into cost_budget (tenant_id, period_month, monthly_cap_usd, "
    "per_run_cap_usd, balance_floor_usd, hard_stop) values "
    "(:tenant_id, date_trunc('month', current_date)::date, "
    ":monthly_cap, :per_run_cap, :balance_floor, true)"
)


def ctx() -> RequestContext:
    return RequestContext(tenant_id=TENANT_ID, actor_id=USER_ID, role="as_admin")


def one_unit(cost: str) -> list[CostUnit]:
    amount = Decimal(cost)
    return [CostUnit(label="units", count=1, unit_cost_usd=amount, subtotal_usd=amount)]


class Recorder:
    """A dispatch stub that counts calls without doing real work."""

    def __init__(self) -> None:
        self.calls = 0

    async def dispatch(self) -> dict[str, object]:
        self.calls += 1
        return {"queued": True}


@pytest.fixture(scope="session")
def database_urls() -> tuple[str, str]:
    api_url = os.environ.get("TEST_API_DATABASE_URL")
    migrator_url = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
    if not api_url or not migrator_url:
        pytest.skip(
            "approval ladder integration tests require TEST_API_DATABASE_URL and "
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
    """A dedicated tenant with a generous default budget, self-contained.

    `tenant` truncation cascades to `location`, `cost_preview`, `approval`,
    `cost_ledger`, and `cost_budget` (all FK to `tenant`). `user_profile` is
    global (no FK to `tenant`), so its insert is idempotent instead.
    """

    async with migrator_engine.begin() as connection:
        await connection.execute(text("truncate tenant cascade"))
        await connection.execute(
            text(
                "insert into tenant (id, slug, name, tier, status) values "
                "(:tenant_id, 'ladder-tests', 'Ladder Tests', 'agency_client', 'active')"
            ),
            {"tenant_id": TENANT_ID},
        )
        await connection.execute(
            text(
                "insert into user_profile (id, email, full_name) values "
                "(:id, 'ladder-tester@example.test', 'Ladder Tester') "
                "on conflict (id) do nothing"
            ),
            {"id": USER_ID},
        )
        await connection.execute(
            BUDGET_INSERT_SQL,
            {
                "tenant_id": TENANT_ID,
                "monthly_cap": 1000.00,
                "per_run_cap": 100.00,
                "balance_floor": 0.00,
            },
        )
    yield


async def make_preview(
    db: AsyncSession,
    *,
    cost: str = "10.00",
    operation: str = "test_op",
) -> dict[str, object]:
    return await approval_ladder.create_preview(
        db,
        tenant_id=TENANT_ID,
        location_id=None,
        operation=operation,
        requested_by=USER_ID,
        params={"k": "v"},
        units=one_unit(cost),
        estimated_cost_usd=Decimal(cost),
        provider_balance_usd=None,
    )


async def test_preview_with_failing_gate_still_succeeds(db: AsyncSession, seed: None) -> None:
    """`passes: false` is a 200, not an exception — only execute() enforces (`05` §4.1)."""

    async with tenant_context(db, ctx()):
        preview = await make_preview(db, cost="500.00")  # exceeds the 100.00 per-run cap

    assert preview["passes"] is False
    assert any(not gate["pass"] for gate in preview["gates"])


async def test_execute_with_expired_preview_raises_preview_expired(
    db: AsyncSession, seed: None
) -> None:
    async with tenant_context(db, ctx()):
        preview = await make_preview(db)
        await db.execute(
            text("update cost_preview set expires_at = now() - interval '1 minute' "
                 "where id = :id"),
            {"id": preview["preview_id"]},
        )
        recorder = Recorder()
        with pytest.raises(ApiProblem) as excinfo:
            await approval_ladder.execute(
                db,
                tenant_id=TENANT_ID,
                location_id=None,
                operation="test_op",
                approved_by=USER_ID,
                preview_id=preview["preview_id"],
                idempotency_key=str(uuid4()),
                reprice_cost_usd=Decimal("10.00"),
                provider_balance_usd=None,
                dispatch=recorder.dispatch,
            )
    assert excinfo.value.code is ProblemCode.PREVIEW_EXPIRED
    assert recorder.calls == 0


async def test_execute_with_price_drift_over_10_percent_raises(
    db: AsyncSession, seed: None
) -> None:
    async with tenant_context(db, ctx()):
        preview = await make_preview(db, cost="10.00")
        recorder = Recorder()
        with pytest.raises(ApiProblem) as excinfo:
            await approval_ladder.execute(
                db,
                tenant_id=TENANT_ID,
                location_id=None,
                operation="test_op",
                approved_by=USER_ID,
                preview_id=preview["preview_id"],
                idempotency_key=str(uuid4()),
                reprice_cost_usd=Decimal("15.00"),  # 50% drift
                provider_balance_usd=None,
                dispatch=recorder.dispatch,
            )
    assert excinfo.value.code is ProblemCode.PREVIEW_PRICE_DRIFT
    assert recorder.calls == 0


async def test_execute_over_budget_raises_and_writes_nothing(
    db: AsyncSession, seed: None
) -> None:
    async with tenant_context(db, ctx()):
        preview = await make_preview(db, cost="100.00")  # exactly at the per-run cap
        recorder = Recorder()
        idempotency_key = str(uuid4())
        with pytest.raises(ApiProblem) as excinfo:
            await approval_ladder.execute(
                db,
                tenant_id=TENANT_ID,
                location_id=None,
                operation="test_op",
                approved_by=USER_ID,
                preview_id=preview["preview_id"],
                idempotency_key=idempotency_key,
                reprice_cost_usd=Decimal("105.00"),  # 5% drift, but over the 100.00 cap
                provider_balance_usd=None,
                dispatch=recorder.dispatch,
            )
        assert excinfo.value.code is ProblemCode.BUDGET_EXCEEDED
        assert recorder.calls == 0

    # assert_budget()'s raise aborts the Postgres transaction server-side;
    # the count check needs a fresh transaction, not the failed one above.
    async with tenant_context(db, ctx()):
        count = (
            await db.execute(
                text("select count(*) from approval where idempotency_key = :key"),
                {"key": idempotency_key},
            )
        ).scalar_one()
    assert count == 0


async def test_idempotent_replay_returns_original_and_dispatches_once(
    db: AsyncSession, seed: None
) -> None:
    async with tenant_context(db, ctx()):
        preview = await make_preview(db, cost="10.00")
        recorder = Recorder()
        idempotency_key = str(uuid4())

        first = await approval_ladder.execute(
            db,
            tenant_id=TENANT_ID,
            location_id=None,
            operation="test_op",
            approved_by=USER_ID,
            preview_id=preview["preview_id"],
            idempotency_key=idempotency_key,
            reprice_cost_usd=Decimal("10.00"),
            provider_balance_usd=None,
            dispatch=recorder.dispatch,
        )
        second = await approval_ladder.execute(
            db,
            tenant_id=TENANT_ID,
            location_id=None,
            operation="test_op",
            approved_by=USER_ID,
            preview_id=preview["preview_id"],
            idempotency_key=idempotency_key,
            reprice_cost_usd=Decimal("10.00"),
            provider_balance_usd=None,
            dispatch=recorder.dispatch,
        )

    assert first["approval_id"] == second["approval_id"]
    assert recorder.calls == 1


async def test_same_key_different_preview_raises_duplicate_idempotency_key(
    db: AsyncSession, seed: None
) -> None:
    async with tenant_context(db, ctx()):
        preview_a = await make_preview(db, cost="10.00")
        preview_b = await make_preview(db, cost="10.00")
        recorder = Recorder()
        idempotency_key = str(uuid4())

        await approval_ladder.execute(
            db,
            tenant_id=TENANT_ID,
            location_id=None,
            operation="test_op",
            approved_by=USER_ID,
            preview_id=preview_a["preview_id"],
            idempotency_key=idempotency_key,
            reprice_cost_usd=Decimal("10.00"),
            provider_balance_usd=None,
            dispatch=recorder.dispatch,
        )

        with pytest.raises(ApiProblem) as excinfo:
            await approval_ladder.execute(
                db,
                tenant_id=TENANT_ID,
                location_id=None,
                operation="test_op",
                approved_by=USER_ID,
                preview_id=preview_b["preview_id"],
                idempotency_key=idempotency_key,
                reprice_cost_usd=Decimal("10.00"),
                provider_balance_usd=None,
                dispatch=recorder.dispatch,
            )
    assert excinfo.value.code is ProblemCode.DUPLICATE_IDEMPOTENCY_KEY
    assert recorder.calls == 1


async def test_missing_idempotency_key_header_raises_validation_error() -> None:
    with pytest.raises(ApiProblem) as excinfo:
        require_idempotency_key(None)

    assert excinfo.value.code is ProblemCode.VALIDATION_ERROR
    assert excinfo.value.status == 422


async def test_concurrent_identical_requests_produce_exactly_one_approval(
    api_engine: AsyncEngine, seed: None
) -> None:
    factory = async_sessionmaker(api_engine, expire_on_commit=False, autoflush=False)
    idempotency_key = str(uuid4())
    recorder = Recorder()

    async with factory() as setup_session:
        async with tenant_context(setup_session, ctx()):
            preview = await make_preview(setup_session, cost="10.00")
    preview_id = preview["preview_id"]

    async def attempt() -> dict[str, object] | ApiProblem:
        async with factory() as session:
            async with tenant_context(session, ctx()):
                try:
                    return await approval_ladder.execute(
                        session,
                        tenant_id=TENANT_ID,
                        location_id=None,
                        operation="test_op",
                        approved_by=USER_ID,
                        preview_id=preview_id,
                        idempotency_key=idempotency_key,
                        reprice_cost_usd=Decimal("10.00"),
                        provider_balance_usd=None,
                        dispatch=recorder.dispatch,
                    )
                except ApiProblem as exc:
                    return exc

    results = await asyncio.gather(attempt(), attempt())

    # Cooperative scheduling means either sub-path is valid: a genuine
    # unique-constraint race yields one error, but it is equally correct for
    # the second attempt to land on the already-committed replay path and
    # succeed too -- both reference the SAME approval either way. What must
    # hold regardless of interleaving is dispatched-once and one row total.
    approval_ids = set()
    for result in results:
        if isinstance(result, ApiProblem):
            assert result.code is ProblemCode.DUPLICATE_IDEMPOTENCY_KEY
        else:
            approval_ids.add(result["approval_id"])
    assert len(approval_ids) <= 1
    assert recorder.calls == 1

    async with factory() as session:
        async with tenant_context(session, ctx()):
            count = (
                await session.execute(
                    text("select count(*) from approval where idempotency_key = :key"),
                    {"key": idempotency_key},
                )
            ).scalar_one()
    assert count == 1
