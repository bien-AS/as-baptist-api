"""Direct PostgreSQL async engine and session lifecycle."""

import asyncio
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings


class DatabaseRuntime:
    """Own one direct PostgreSQL pool and its session factory."""

    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def check_ready(self) -> bool:
        """Ping PostgreSQL inside an explicit transaction."""

        async def ping() -> None:
            async with self.session_factory() as session:
                async with session.begin():
                    await session.execute(text("select 1"))

        try:
            await asyncio.wait_for(ping(), timeout=2.0)
        except (SQLAlchemyError, TimeoutError, OSError):
            return False
        return True

    async def dispose(self) -> None:
        """Close pooled connections during application shutdown."""

        await self.engine.dispose()


def get_database(request: Request) -> DatabaseRuntime:
    """Resolve the runtime created by the application factory."""

    database = getattr(request.app.state, "database", None)
    if not isinstance(database, DatabaseRuntime):
        raise RuntimeError("database runtime is not configured")
    return database


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a session; callers must open an explicit transaction boundary."""

    database = get_database(request)
    async with database.session_factory() as session:
        yield session


def default_database() -> DatabaseRuntime:
    """Create the process default for scripts that do not have a Request."""

    return DatabaseRuntime(get_settings())
