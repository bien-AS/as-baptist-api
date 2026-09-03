"""`ResponseMeta`/`PageInfo` construction shared by every domain router (`05` §2)."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import Request

from app.db.rls import RequestContext
from app.schemas.common import DataSource, PageInfo, ResponseMeta, ResponseScope


def build_meta(
    request: Request,
    ctx: RequestContext,
    *,
    source: DataSource | Literal["mixed"] | str,
    as_of: str | None = None,
    stale: bool = False,
    location: str | None = None,
) -> ResponseMeta:
    """Build the provenance envelope every 2xx domain read must carry.

    `source` accepts a raw string (e.g. straight from an ORM column) as a
    convenience for callers — it is resolved against `DataSource` here so the
    type mismatch is caught at the one place that matters, not duplicated in
    every router.
    """

    resolved_source: DataSource | Literal["mixed"]
    if isinstance(source, DataSource):
        resolved_source = source
    elif source == "mixed":
        resolved_source = "mixed"
    else:
        resolved_source = DataSource(source)
    request_id = getattr(request.state, "request_id", "unknown")
    return ResponseMeta(
        request_id=request_id,
        generated_at=datetime.now(UTC),
        as_of=as_of,
        source=resolved_source,
        stale=stale,
        scope=ResponseScope(tenant=str(ctx.tenant_id), location=location),
    )


def build_page(*, limit: int, offset: int, total: int) -> PageInfo:
    """Build the pagination envelope for `Paginated[T]` responses."""

    return PageInfo(limit=limit, offset=offset, total=total, has_more=offset + limit < total)
