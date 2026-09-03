"""Location HTTP routes — validate, call the service, return (`01` §3)."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import build_meta, build_page
from app.core.errors import ApiProblem
from app.db.rls import RequestContext
from app.deps import get_scoped_db, require_operator, tenant_context_dependency
from app.repositories.location import LocationRepository
from app.schemas import Envelope, Paginated, ProblemCode
from app.schemas.location import (
    LocationCreate,
    LocationDetail,
    LocationSummary,
    LocationUpdate,
)
from app.services.location import LocationService

router = APIRouter(prefix="/v1/locations", tags=["locations"])

scoped_db_dependency = Depends(get_scoped_db)
operator_context_dependency = Depends(require_operator)


def get_location_service(session: AsyncSession = scoped_db_dependency) -> LocationService:
    return LocationService(LocationRepository(session))


location_service_dependency = Depends(get_location_service)


@router.get("", response_model=Paginated[LocationSummary])
async def list_locations(
    request: Request,
    ctx: RequestContext = tenant_context_dependency,
    service: LocationService = location_service_dependency,
    fleet: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> Paginated[LocationSummary]:
    locations, total = await service.list_locations(
        limit=limit,
        offset=offset,
        fleet=fleet,
        status=status,
        q=q,
    )
    return Paginated(
        data=[LocationSummary.from_model(location) for location in locations],
        page=build_page(limit=limit, offset=offset, total=total),
        meta=build_meta(request, ctx, source="computed"),
    )


@router.get("/{slug}", response_model=Envelope[LocationDetail])
async def get_location(
    slug: str,
    request: Request,
    ctx: RequestContext = tenant_context_dependency,
    service: LocationService = location_service_dependency,
) -> Envelope[LocationDetail]:
    location = await service.get_by_slug(slug)
    if location is None:
        raise ApiProblem.from_code(ProblemCode.NOT_FOUND)
    return Envelope(
        data=LocationDetail.from_model(location),
        meta=build_meta(request, ctx, source=location.source, location=location.slug),
    )


@router.post("", response_model=Envelope[LocationDetail], status_code=201)
async def create_location(
    payload: LocationCreate,
    request: Request,
    ctx: RequestContext = operator_context_dependency,
    service: LocationService = location_service_dependency,
) -> Envelope[LocationDetail]:
    location = await service.create(ctx.tenant_id, payload)
    return Envelope(
        data=LocationDetail.from_model(location),
        meta=build_meta(request, ctx, source=location.source, location=location.slug),
    )


@router.patch("/{slug}", response_model=Envelope[LocationDetail])
async def update_location(
    slug: str,
    payload: LocationUpdate,
    request: Request,
    ctx: RequestContext = operator_context_dependency,
    service: LocationService = location_service_dependency,
) -> Envelope[LocationDetail]:
    location = await service.get_by_slug(slug)
    if location is None:
        raise ApiProblem.from_code(ProblemCode.NOT_FOUND)
    location = await service.update(location, payload)
    return Envelope(
        data=LocationDetail.from_model(location),
        meta=build_meta(request, ctx, source=location.source, location=location.slug),
    )
