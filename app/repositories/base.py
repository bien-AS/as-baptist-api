"""Generic pagination-aware repository shared by every domain.

No repository here filters by tenant — isolation comes entirely from RLS.
`scripts/check_architecture.py` fails the build if a manual tenant equality
filter appears in this package (`01` §2, `02` §2).
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


class BaseRepository[ModelT: DeclarativeBase]:
    """CRUD + pagination helpers parameterised over one SQLAlchemy model."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, **filters: Any) -> ModelT | None:
        stmt = select(self.model).filter_by(**filters)
        return (await self._session.scalars(stmt)).one_or_none()

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> tuple[Sequence[ModelT], int]:
        stmt = select(self.model).filter_by(**filters)
        total = (
            await self._session.scalar(select(func.count()).select_from(stmt.subquery()))
        ) or 0
        rows = (await self._session.scalars(stmt.limit(limit).offset(offset))).all()
        return rows, total

    async def create(self, **values: Any) -> ModelT:
        instance = self.model(**values)
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def update(self, instance: ModelT, **values: Any) -> ModelT:
        for field, value in values.items():
            setattr(instance, field, value)
        await self._session.flush()
        return instance
