"""RFC 9457 error models, catalog, and FastAPI exception handlers."""

from collections.abc import Sequence
from typing import Final, NamedTuple

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from structlog.stdlib import BoundLogger

from app.schemas import FieldError, Problem, ProblemCode


class ProblemDefinition(NamedTuple):
    """Default HTTP metadata for one stable problem code."""

    status: int
    title: str
    detail: str


PROBLEM_DEFINITIONS: Final[dict[ProblemCode, ProblemDefinition]] = {
    ProblemCode.UNAUTHENTICATED: ProblemDefinition(
        401, "Unauthenticated", "Authentication is required."
    ),
    ProblemCode.TOKEN_EXPIRED: ProblemDefinition(
        401, "Token expired", "The access token has expired."
    ),
    ProblemCode.TENANT_SCOPE_MISSING: ProblemDefinition(
        403, "Tenant scope missing", "The token has no tenant scope."
    ),
    ProblemCode.FORBIDDEN_ROLE: ProblemDefinition(
        403, "Forbidden role", "This operation is not available for your role."
    ),
    ProblemCode.LOCATION_OUT_OF_SCOPE: ProblemDefinition(
        403, "Location out of scope", "The location is outside your assigned scope."
    ),
    ProblemCode.NOT_FOUND: ProblemDefinition(
        404, "Not found", "The requested resource was not found."
    ),
    ProblemCode.CONFLICT: ProblemDefinition(
        409, "Conflict", "The resource changed before this operation completed."
    ),
    ProblemCode.DUPLICATE_IDEMPOTENCY_KEY: ProblemDefinition(
        409,
        "Duplicate idempotency key",
        "The idempotency key was already used with a different payload.",
    ),
    ProblemCode.PREVIEW_EXPIRED: ProblemDefinition(
        410, "Preview expired", "The cost preview has expired."
    ),
    ProblemCode.PREVIEW_PRICE_DRIFT: ProblemDefinition(
        412,
        "Preview price drift",
        "The current price differs materially from the preview.",
    ),
    ProblemCode.VALIDATION_ERROR: ProblemDefinition(
        422, "Validation error", "The request did not match the API contract."
    ),
    ProblemCode.PHI_GATE_FAILED: ProblemDefinition(
        422, "PHI gate failed", "The content did not pass the PHI check."
    ),
    ProblemCode.BUDGET_EXCEEDED: ProblemDefinition(
        402,
        "Budget exceeded",
        "The requested operation exceeds the configured budget.",
    ),
    ProblemCode.BALANCE_FLOOR: ProblemDefinition(
        402,
        "Balance floor",
        "The operation would breach the provider balance floor.",
    ),
    ProblemCode.MODULE_DISABLED: ProblemDefinition(
        423, "Module disabled", "This module is disabled for the current scope."
    ),
    ProblemCode.RATE_LIMITED: ProblemDefinition(
        429, "Rate limited", "Too many requests; try again later."
    ),
    ProblemCode.PROVIDER_ERROR: ProblemDefinition(
        502, "Provider error", "An upstream provider failed."
    ),
    ProblemCode.PROVIDER_BLOCKED: ProblemDefinition(
        503, "Provider blocked", "An upstream provider rejected the request."
    ),
    ProblemCode.INTERNAL_ERROR: ProblemDefinition(
        500, "Internal error", "An unexpected error occurred."
    ),
}


class ApiProblem(Exception):
    """Expected application error rendered as an RFC 9457 response."""

    def __init__(
        self,
        code: ProblemCode,
        *,
        detail: str | None = None,
        instance: str | None = None,
        errors: Sequence[FieldError] | None = None,
        status: int | None = None,
        title: str | None = None,
    ) -> None:
        definition = PROBLEM_DEFINITIONS[code]
        self.code = code
        self.detail = detail or definition.detail
        self.instance = instance
        self.errors = list(errors) if errors is not None else None
        self.status = status or definition.status
        self.title = title or definition.title
        super().__init__(self.detail)

    @classmethod
    def from_code(
        cls,
        code: ProblemCode,
        *,
        detail: str | None = None,
        instance: str | None = None,
        errors: Sequence[FieldError] | None = None,
        status: int | None = None,
        title: str | None = None,
    ) -> "ApiProblem":
        """Construct a catalogued problem without repeating its defaults."""

        return cls(
            code,
            detail=detail,
            instance=instance,
            errors=errors,
            status=status,
            title=title,
        )


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) and request_id else "unknown"


def problem_response(request: Request, problem: ApiProblem) -> JSONResponse:
    """Render one problem without exposing exception internals."""

    request_id = _request_id(request)
    body = Problem(
        type=f"https://api.baptist-gbp.com/errors/{problem.code.value.lower()}",
        title=problem.title,
        status=problem.status,
        detail=problem.detail,
        instance=problem.instance or request.url.path,
        code=problem.code,
        request_id=request_id,
        errors=problem.errors,
    )
    return JSONResponse(
        status_code=problem.status,
        content=body.model_dump(mode="json", exclude_none=True),
        media_type="application/problem+json",
        headers={"X-Request-ID": request_id},
    )


async def api_problem_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiProblem):
        return await unhandled_exception_handler(request, exc)
    return problem_response(request, exc)


async def validation_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        return await unhandled_exception_handler(request, exc)
    errors = [
        FieldError(
            field=(
                ".".join(str(part) for part in error.get("loc", ()) if part != "body")
                or "request"
            ),
            message=str(error.get("msg", "Invalid value")),
        )
        for error in exc.errors()
    ]
    problem = ApiProblem.from_code(ProblemCode.VALIDATION_ERROR, errors=errors)
    return problem_response(request, problem)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log server detail while returning only a safe generic response."""

    logger: BoundLogger = request.app.state.logger
    logger.exception(
        "unhandled_exception",
        path=request.url.path,
        exception_type=type(exc).__name__,
    )
    problem = ApiProblem.from_code(ProblemCode.INTERNAL_ERROR)
    return problem_response(request, problem)
