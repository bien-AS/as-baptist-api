"""Transaction-scoped tenant context; the sole SET LOCAL boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Identity values bound to one database transaction."""

    tenant_id: UUID
    actor_id: UUID
    role: str


@asynccontextmanager
async def tenant_context(
    session: AsyncSession,
    ctx: RequestContext,
) -> AsyncIterator[AsyncSession]:
    """Bind tenant, actor, and role for one explicit transaction."""

    if session.in_transaction():
        raise RuntimeError("tenant_context requires a session without an open transaction")
    async with session.begin():
        await session.execute(
            text(
                "SELECT set_config('app.tenant_id', :tenant_id, true), "
                "set_config('app.actor_id', :actor_id, true), "
                "set_config('app.role', :role, true)"
            ),
            {
                "tenant_id": str(ctx.tenant_id),
                "actor_id": str(ctx.actor_id),
                "role": ctx.role,
            },
        )
        yield session
