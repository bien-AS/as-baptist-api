"""The required `Idempotency-Key` header on every spend-bearing POST (`05` §5)."""

from fastapi import Header

from app.core.errors import ApiProblem
from app.schemas import ProblemCode


def require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    """A missing key is a validation error, not a silent default."""

    if not idempotency_key:
        raise ApiProblem.from_code(
            ProblemCode.VALIDATION_ERROR,
            detail="The Idempotency-Key header is required.",
        )
    return idempotency_key
