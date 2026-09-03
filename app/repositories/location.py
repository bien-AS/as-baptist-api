"""Location repository."""

from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.location import Location
from app.repositories.base import BaseRepository


class LocationRepository(BaseRepository[Location]):
    model = Location

    async def get_by_slug(self, slug: str) -> Location | None:
        return await self.get(slug=slug)

    async def list_locations(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        fleet: str | None = None,
        status: str | None = None,
        q: str | None = None,
    ) -> tuple[Sequence[Location], int]:
        stmt = select(Location)
        if fleet is not None:
            stmt = stmt.where(Location.fleet == fleet)
        if status is not None:
            stmt = stmt.where(Location.status == status)
        if q is not None:
            stmt = stmt.where(Location.name.ilike(f"%{q}%"))

        total = (
            await self._session.scalar(select(func.count()).select_from(stmt.subquery()))
        ) or 0
        rows = (
            await self._session.scalars(stmt.order_by(Location.name).limit(limit).offset(offset))
        ).all()
        return rows, total
