"""Shared transport models; domain contracts will be generated separately."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ProblemCode(StrEnum):
    """The stable error-code catalog from the API contract."""

    UNAUTHENTICATED = "UNAUTHENTICATED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TENANT_SCOPE_MISSING = "TENANT_SCOPE_MISSING"
    FORBIDDEN_ROLE = "FORBIDDEN_ROLE"
    LOCATION_OUT_OF_SCOPE = "LOCATION_OUT_OF_SCOPE"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    DUPLICATE_IDEMPOTENCY_KEY = "DUPLICATE_IDEMPOTENCY_KEY"
    PREVIEW_EXPIRED = "PREVIEW_EXPIRED"
    PREVIEW_PRICE_DRIFT = "PREVIEW_PRICE_DRIFT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PHI_GATE_FAILED = "PHI_GATE_FAILED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    BALANCE_FLOOR = "BALANCE_FLOOR"
    MODULE_DISABLED = "MODULE_DISABLED"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PROVIDER_BLOCKED = "PROVIDER_BLOCKED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class FieldError(BaseModel):
    """A field-level validation detail in a Problem response."""

    model_config = ConfigDict(extra="forbid")

    field: str
    message: str


class Problem(BaseModel):
    """RFC 9457 problem details plus the stable Baptist error extensions."""

    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: ProblemCode
    request_id: str
    errors: list[FieldError] | None = None


class HealthResponse(BaseModel):
    """Liveness response."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


class ReadyResponse(BaseModel):
    """Readiness response."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"]


class DataSource(StrEnum):
    """Provenance catalog — mirrors the `data_source` Postgres enum (`03` §1)."""

    SEARCHATLAS = "searchatlas"
    DATAFORSEO = "dataforseo"
    SERPER = "serper"
    BRIGHTLOCAL = "brightlocal"
    SYNTHETIC = "synthetic"
    COMPUTED = "computed"
    CLIENT_VERIFIED = "client_verified"


class ResponseScope(BaseModel):
    """The tenant/location a response is scoped to."""

    model_config = ConfigDict(extra="forbid")

    tenant: str
    location: str | None = None


class ResponseMeta(BaseModel):
    """Provenance envelope carried on every domain read (`05` §2)."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    generated_at: datetime
    as_of: str | None = None
    source: DataSource | Literal["mixed"]
    sources: list[DataSource] | None = None
    stale: bool = False
    scope: ResponseScope


class PageInfo(BaseModel):
    """Offset pagination metadata for `Paginated[T]`."""

    model_config = ConfigDict(extra="forbid")

    limit: int
    offset: int
    total: int
    has_more: bool


class Envelope[T](BaseModel):
    """The single-resource response wrapper — every 2xx body uses this or `Paginated`."""

    model_config = ConfigDict(extra="forbid")

    data: T
    meta: ResponseMeta


class Paginated[T](BaseModel):
    """The collection response wrapper for offset-paginated domain reads."""

    model_config = ConfigDict(extra="forbid")

    data: list[T]
    page: PageInfo
    meta: ResponseMeta
