"""The shared preview -> approve -> execute primitive (`05` §4).

Pricing is domain-specific and lives in the caller — this module owns exactly
what the contract specifies as shared: storing the preview, evaluating spend
gates, and the execute-time sequence (re-price check, budget assertion, the
idempotent approval row, dispatch, and the audit card) inside one transaction.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiProblem
from app.schemas import ProblemCode
from app.services import audit as audit_service

DRIFT_TOLERANCE = Decimal("0.10")

DispatchFn = Callable[[], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class CostUnit:
    """One priced line item, e.g. `{label: "pins", count: 100, ...}` (`05` §4.1)."""

    label: str
    count: int
    unit_cost_usd: Decimal
    subtotal_usd: Decimal

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "count": self.count,
            "unit_cost_usd": str(self.unit_cost_usd),
            "subtotal_usd": str(self.subtotal_usd),
        }


async def create_preview(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    location_id: UUID | None,
    operation: str,
    requested_by: UUID,
    params: dict[str, Any],
    units: list[CostUnit],
    estimated_cost_usd: Decimal,
    provider_balance_usd: Decimal | None,
) -> dict[str, Any]:
    """Step 1 — free, no side effects beyond recording the priced quote.

    `passes: false` is a valid, successful result: the preview succeeded, the
    *spend* would not (`05` §4.1). Only `execute()` ever raises for a gate.
    """

    gates = await _evaluate_gates(
        session,
        estimated_cost_usd=estimated_cost_usd,
        provider_balance_usd=provider_balance_usd,
    )
    passes = all(gate["pass"] for gate in gates)

    row = (
        await session.execute(
            text(
                "insert into cost_preview "
                "(tenant_id, location_id, operation, requested_by, params, units, "
                " estimated_cost_usd, gates, passes) "
                "values (:tenant_id, :location_id, :operation, :requested_by, "
                " cast(:params as jsonb), cast(:units as jsonb), :estimated_cost_usd, "
                " cast(:gates as jsonb), :passes) "
                "returning id, expires_at"
            ),
            {
                "tenant_id": tenant_id,
                "location_id": location_id,
                "operation": operation,
                "requested_by": requested_by,
                "params": json.dumps(params, default=str),
                "units": json.dumps([unit.as_dict() for unit in units]),
                "estimated_cost_usd": estimated_cost_usd,
                "gates": json.dumps(gates),
                "passes": passes,
            },
        )
    ).one()

    return {
        "preview_id": row.id,
        "operation": operation,
        "expires_at": row.expires_at,
        "units": [unit.as_dict() for unit in units],
        "estimated_cost_usd": estimated_cost_usd,
        "gates": gates,
        "passes": passes,
    }


async def _evaluate_gates(
    session: AsyncSession,
    *,
    estimated_cost_usd: Decimal,
    provider_balance_usd: Decimal | None,
) -> list[dict[str, Any]]:
    """Advisory checks mirroring `cost.assert_budget()` for display purposes.

    The database function remains the sole enforcement point at execute time
    (`04` §5.4) — this is presentation only, so the ladder cannot spend around
    a gate it forgot to reimplement correctly in Python.
    """

    budget = (
        await session.execute(
            text(
                "select monthly_cap_usd, per_run_cap_usd, balance_floor_usd, hard_stop "
                "from cost_budget where tenant_id = app.current_tenant_id() "
                "and period_month = date_trunc('month', current_date)::date"
            )
        )
    ).one_or_none()

    if budget is None:
        return [
            {
                "id": "budget_configured",
                "pass": False,
                "detail": "No cost budget configured for this tenant/month.",
            }
        ]

    spent = Decimal((await session.execute(text("select cost.month_spend()"))).scalar_one())

    gates: list[dict[str, Any]] = [
        {
            "id": "per_run_cap",
            "pass": estimated_cost_usd <= budget.per_run_cap_usd,
            "detail": f"${estimated_cost_usd:.2f} <= ${budget.per_run_cap_usd:.2f}",
        },
        {
            "id": "monthly_cap",
            "pass": not budget.hard_stop
            or (spent + estimated_cost_usd) <= budget.monthly_cap_usd,
            "detail": (
                f"${spent:.2f} + ${estimated_cost_usd:.2f} <= ${budget.monthly_cap_usd:.2f}"
            ),
        },
    ]
    if provider_balance_usd is not None:
        remaining = provider_balance_usd - estimated_cost_usd
        gates.append(
            {
                "id": "balance_floor",
                "pass": remaining >= budget.balance_floor_usd,
                "detail": f"${remaining:.2f} >= ${budget.balance_floor_usd:.2f}",
            }
        )
    return gates


async def execute(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    location_id: UUID | None,
    operation: str,
    approved_by: UUID,
    preview_id: UUID,
    idempotency_key: str,
    reprice_cost_usd: Decimal,
    provider_balance_usd: Decimal | None,
    dispatch: DispatchFn,
) -> dict[str, Any]:
    """Steps 2-8 of `05` §4.2, inside one transaction.

    A concurrent race on the same idempotency key is resolved by the unique
    constraint on `(tenant_id, idempotency_key)`: exactly one INSERT wins, the
    other raises `DUPLICATE_IDEMPOTENCY_KEY` rather than blocking to await the
    winner's result. A *sequential* replay (the common case) finds the already
    -committed row via `_find_existing_approval` and returns it directly.
    """

    existing = await _find_existing_approval(session, tenant_id, idempotency_key)
    if existing is not None:
        if existing.cost_preview_id != preview_id:
            raise ApiProblem.from_code(ProblemCode.DUPLICATE_IDEMPOTENCY_KEY)
        return existing.response

    preview = await _load_preview(session, tenant_id, operation, preview_id)
    if preview is None:
        raise ApiProblem.from_code(ProblemCode.NOT_FOUND)
    if preview["expires_at"] < datetime.now(UTC):
        raise ApiProblem.from_code(ProblemCode.PREVIEW_EXPIRED)

    baseline = preview["estimated_cost_usd"]
    drift = abs(reprice_cost_usd - baseline) / baseline if baseline else Decimal(0)
    if drift > DRIFT_TOLERANCE:
        raise ApiProblem.from_code(ProblemCode.PREVIEW_PRICE_DRIFT)

    try:
        await session.execute(
            text("select cost.assert_budget(:projected, :balance)"),
            {"projected": reprice_cost_usd, "balance": provider_balance_usd},
        )
    except DBAPIError as exc:
        raise ApiProblem.from_code(ProblemCode.BUDGET_EXCEEDED) from exc

    try:
        approval_row = (
            await session.execute(
                text(
                    "insert into approval (tenant_id, location_id, cost_preview_id, "
                    "operation, approved_by, idempotency_key, status) "
                    "values (:tenant_id, :location_id, :preview_id, :operation, "
                    ":approved_by, :idempotency_key, 'executing') returning id"
                ),
                {
                    "tenant_id": tenant_id,
                    "location_id": location_id,
                    "preview_id": preview_id,
                    "operation": operation,
                    "approved_by": approved_by,
                    "idempotency_key": idempotency_key,
                },
            )
        ).one()
    except IntegrityError as exc:
        raise ApiProblem.from_code(ProblemCode.DUPLICATE_IDEMPOTENCY_KEY) from exc

    result = await dispatch()

    await session.execute(
        text(
            "update approval set status = 'executed', executed_at = now(), "
            "actual_cost_usd = :cost, result = cast(:result as jsonb) "
            "where id = :id"
        ),
        {
            "cost": reprice_cost_usd,
            "result": json.dumps(result, default=str),
            "id": approval_row.id,
        },
    )

    await audit_service.write_card(
        session,
        location_id=location_id,
        verb="execute",
        action=f"Executed {operation}",
        resource_type=operation,
        resource_id=str(approval_row.id),
        approval_id=approval_row.id,
    )

    return {
        "approval_id": approval_row.id,
        "status": "executed",
        "actual_cost_usd": reprice_cost_usd,
        "result": result,
    }


async def _load_preview(
    session: AsyncSession,
    tenant_id: UUID,
    operation: str,
    preview_id: UUID,
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "select estimated_cost_usd, expires_at from cost_preview "
                "where id = :id and tenant_id = :tenant_id and operation = :operation"
            ),
            {"id": preview_id, "tenant_id": tenant_id, "operation": operation},
        )
    ).one_or_none()
    if row is None:
        return None
    return {"estimated_cost_usd": row.estimated_cost_usd, "expires_at": row.expires_at}


@dataclass(frozen=True, slots=True)
class _ExistingApproval:
    cost_preview_id: UUID | None
    response: dict[str, Any]


async def _find_existing_approval(
    session: AsyncSession,
    tenant_id: UUID,
    idempotency_key: str,
) -> _ExistingApproval | None:
    row = (
        await session.execute(
            text(
                "select id, cost_preview_id, status, actual_cost_usd, result "
                "from approval where tenant_id = :tenant_id and idempotency_key = :key"
            ),
            {"tenant_id": tenant_id, "key": idempotency_key},
        )
    ).one_or_none()
    if row is None:
        return None
    return _ExistingApproval(
        cost_preview_id=row.cost_preview_id,
        response={
            "approval_id": row.id,
            "status": row.status,
            "actual_cost_usd": row.actual_cost_usd,
            "result": row.result,
        },
    )
