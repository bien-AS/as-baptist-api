"""Real-PostgreSQL fixtures for the RLS release gate."""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@dataclass(frozen=True, slots=True)
class Seed:
    tenant_a: UUID = UUID("00000000-0000-0000-0000-00000000000a")
    tenant_b: UUID = UUID("00000000-0000-0000-0000-00000000000b")
    user_a: UUID = UUID("00000000-0000-0000-0000-00000000001a")
    user_b: UUID = UUID("00000000-0000-0000-0000-00000000001b")
    membership_a: UUID = UUID("00000000-0000-0000-0000-00000000002a")
    membership_b: UUID = UUID("00000000-0000-0000-0000-00000000002b")


@pytest.fixture(scope="session")
def database_urls() -> tuple[str, str, str | None]:
    api_url = os.environ.get("TEST_API_DATABASE_URL")
    migrator_url = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
    worker_url = os.environ.get("TEST_WORKER_DATABASE_URL")
    if not api_url or not migrator_url:
        pytest.skip(
            "RLS integration tests require TEST_API_DATABASE_URL and "
            "TEST_MIGRATIONS_DATABASE_URL"
        )
    return api_url, migrator_url, worker_url


@pytest_asyncio.fixture(scope="session")
async def api_engine(
    database_urls: tuple[str, str, str | None],
) -> AsyncIterator[AsyncEngine]:
    api_url, _, _ = database_urls
    engine = create_async_engine(
        api_url,
        pool_size=4,
        max_overflow=0,
        pool_pre_ping=True,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def migrator_engine(
    database_urls: tuple[str, str, str | None],
) -> AsyncIterator[AsyncEngine]:
    _, migrator_url, _ = database_urls
    engine = create_async_engine(migrator_url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(api_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(api_engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def seed(migrator_engine: AsyncEngine) -> AsyncIterator[Seed]:
    value = Seed()
    async with migrator_engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE membership_location, membership, tenant_credential, "
                "user_profile, tenant CASCADE"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO tenant (id, slug, name, tier, status) VALUES "
                "(:tenant_a, 'rls-a', 'RLS Tenant A', 'agency_client', 'active'), "
                "(:tenant_b, 'rls-b', 'RLS Tenant B', 'agency_client', 'active')"
            ),
            {"tenant_a": value.tenant_a, "tenant_b": value.tenant_b},
        )
        await connection.execute(
            text(
                "INSERT INTO user_profile (id, email, full_name) VALUES "
                "(:user_a, 'rls-a@example.test', 'RLS A'), "
                "(:user_b, 'rls-b@example.test', 'RLS B')"
            ),
            {"user_a": value.user_a, "user_b": value.user_b},
        )
        await connection.execute(
            text(
                "INSERT INTO membership "
                "(id, tenant_id, user_id, role, status) VALUES "
                "(:membership_a, :tenant_a, :user_a, 'as_admin', 'active'), "
                "(:membership_b, :tenant_b, :user_b, 'as_admin', 'active')"
            ),
            {
                "membership_a": value.membership_a,
                "membership_b": value.membership_b,
                "tenant_a": value.tenant_a,
                "tenant_b": value.tenant_b,
                "user_a": value.user_a,
                "user_b": value.user_b,
            },
        )
    yield value


@pytest_asyncio.fixture
async def worker_db(
    database_urls: tuple[str, str, str | None],
) -> AsyncIterator[AsyncSession]:
    _, _, worker_url = database_urls
    if not worker_url:
        pytest.skip("worker RLS integration test requires TEST_WORKER_DATABASE_URL")
    engine = create_async_engine(
        worker_url,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
    await engine.dispose()
