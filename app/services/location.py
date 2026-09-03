"""Location domain business rules — thin; DB constraints do the real validation."""

from collections.abc import Sequence
from uuid import UUID

from app.models.location import Location
from app.repositories.location import LocationRepository
from app.schemas.location import LocationCreate, LocationUpdate


class LocationService:
    def __init__(self, repository: LocationRepository) -> None:
        self._repository = repository

    async def get_by_slug(self, slug: str) -> Location | None:
        return await self._repository.get_by_slug(slug)

    async def list_locations(
        self,
        *,
        limit: int,
        offset: int,
        fleet: str | None,
        status: str | None,
        q: str | None,
    ) -> tuple[Sequence[Location], int]:
        return await self._repository.list_locations(
            limit=limit,
            offset=offset,
            fleet=fleet,
            status=status,
            q=q,
        )

    async def create(self, tenant_id: UUID, payload: LocationCreate) -> Location:
        return await self._repository.create(tenant_id=tenant_id, **payload.model_dump())

    async def update(self, location: Location, payload: LocationUpdate) -> Location:
        changes = payload.model_dump(exclude_unset=True)
        return await self._repository.update(location, **changes)
