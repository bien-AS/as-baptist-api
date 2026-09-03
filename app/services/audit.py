"""The append-only audit trail. Every write goes through `audit.write_card()`."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WRITE_CARD_SQL = text(
    "select audit.write_card("
    ":location_id, :verb, :action, :resource_type, "
    ":resource_id, :approval_id, cast(:detail as jsonb), :simulated)"
)


async def write_card(
    session: AsyncSession,
    *,
    location_id: UUID | None,
    verb: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    approval_id: UUID | None = None,
    detail: dict[str, Any] | None = None,
    simulated: bool = False,
) -> int:
    """Append one audit card. Requires an active `tenant_context()` transaction.

    The actor is resolved server-side from session context by the function
    itself — nothing here can spoof who performed the action.
    """

    result = await session.execute(
        WRITE_CARD_SQL,
        {
            "location_id": location_id,
            "verb": verb,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "approval_id": approval_id,
            "detail": json.dumps(detail) if detail is not None else None,
            "simulated": simulated,
        },
    )
    return int(result.scalar_one())
