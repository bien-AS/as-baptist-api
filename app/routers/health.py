"""Unauthenticated liveness and database readiness endpoints."""

from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import APIRouter, Depends, Request

from app.core.errors import ApiProblem
from app.schemas import HealthResponse, ProblemCode, ReadyResponse

ReadinessProbe = Callable[[], Awaitable[bool]]

router = APIRouter(prefix="/v1", tags=["system"])


async def unavailable_readiness_probe() -> bool:
    """Safe phase-2 default; phase 3 replaces this with a DB ping."""

    return False


def get_readiness_probe(request: Request) -> ReadinessProbe:
    probe = getattr(request.app.state, "readiness_probe", unavailable_readiness_probe)
    if not callable(probe):
        return unavailable_readiness_probe
    return cast(ReadinessProbe, probe)


readiness_dependency = Depends(get_readiness_probe)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return 200 when the process is alive; no external dependency is checked."""

    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def ready(probe: ReadinessProbe = readiness_dependency) -> ReadyResponse:
    """Return 503 until the configured database readiness probe succeeds."""

    try:
        is_ready = await probe()
    except Exception:
        is_ready = False
    if not is_ready:
        raise ApiProblem.from_code(
            ProblemCode.INTERNAL_ERROR,
            status=503,
            title="Service unavailable",
            detail="The database is not ready.",
        )
    return ReadyResponse(status="ready")
