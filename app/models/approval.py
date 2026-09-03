"""Cost preview and approval models — the approval ladder's storage (`03` §5)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TenantMixin


class CostPreview(TenantMixin, Base):
    """Step 1 of the ladder. Advisory — the server re-prices at execute time."""

    __tablename__ = "cost_preview"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    location_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("location.id")
    )
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("user_profile.id"), nullable=False
    )
    params: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    units: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    gates: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    passes: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now() + interval '15 minutes'"),
    )


class Approval(TenantMixin, Base):
    """Step 2. One approval, one execution — enforced by the idempotency key."""

    __tablename__ = "approval"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    location_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("location.id")
    )
    cost_preview_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("cost_preview.id")
    )
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("user_profile.id"), nullable=False
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="approved")
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint(
            "status in ('approved','executing','executed','failed','expired')",
            name="approval_status_check",
        ),
        UniqueConstraint("tenant_id", "idempotency_key"),
    )
