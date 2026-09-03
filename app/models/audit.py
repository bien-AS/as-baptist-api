"""Audit card model. Append-only — writes go through `audit.write_card()` only."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TenantMixin

actor_role_type = ENUM(
    "as_admin",
    "as_staff",
    "client_admin",
    "client_user",
    "system",
    name="actor_role",
    create_type=False,
    validate_strings=True,
)
data_source_type = ENUM(
    "searchatlas",
    "dataforseo",
    "serper",
    "brightlocal",
    "synthetic",
    "computed",
    "client_verified",
    name="data_source",
    create_type=False,
    validate_strings=True,
)


class AuditCard(TenantMixin, Base):
    """Append-only activity ledger — see `audit.write_card()` (`04` §5.3)."""

    __tablename__ = "audit_card"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    location_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("location.id")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("user_profile.id")
    )
    actor_label: Mapped[str] = mapped_column(Text, nullable=False)
    actor_role: Mapped[str] = mapped_column(actor_role_type, nullable=False)
    verb: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(Text)
    approval_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True))
    request_id: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    source: Mapped[str] = mapped_column(
        data_source_type, nullable=False, server_default="computed"
    )

    __table_args__ = (
        CheckConstraint(
            "verb in ('create','update','delete','approve','reject','read','execute')",
            name="audit_card_verb_check",
        ),
        Index("ix_audit_card__tenant_time", "tenant_id", "occurred_at"),
        Index("ix_audit_card__resource", "tenant_id", "resource_type", "resource_id"),
        Index("ix_audit_card__location", "tenant_id", "location_id", "occurred_at"),
    )
