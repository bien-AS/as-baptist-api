"""Location domain SQLAlchemy models."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TenantMixin, TimestampMixin

fleet_kind_type = ENUM(
    "hospital",
    "clinic",
    name="fleet_kind",
    create_type=False,
    validate_strings=True,
)
listing_type_type = ENUM(
    "facility",
    "department",
    "practitioner",
    name="listing_type",
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


class Location(TenantMixin, TimestampMixin, Base):
    """A tenant-owned facility, department, or practitioner listing."""

    __tablename__ = "location"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    fleet: Mapped[str | None] = mapped_column(fleet_kind_type)
    listing_type: Mapped[str] = mapped_column(listing_type_type, nullable=False)
    facility_type: Mapped[str] = mapped_column(Text, nullable=False)

    address: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    zip: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))

    place_id: Mapped[str | None] = mapped_column(Text)
    cid: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    primary_category: Mapped[str | None] = mapped_column(Text)
    additional_categories: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'"),
    )

    is_claimed: Mapped[bool | None] = mapped_column(Boolean)
    is_verified: Mapped[bool | None] = mapped_column(Boolean)
    total_photos: Mapped[int | None] = mapped_column(Integer)
    rating_value: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    rating_votes: Mapped[int | None] = mapped_column(Integer)
    rating_distribution: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    work_time: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    attributes: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    place_topics: Mapped[dict[str, object] | None] = mapped_column(JSONB)

    searchatlas_business_id: Mapped[int | None] = mapped_column(Integer)
    searchatlas_audit_report_id: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    enriched: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    source: Mapped[str] = mapped_column(data_source_type, nullable=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug"),
        CheckConstraint(
            "status in ('active','onboarding','paused','archived')",
            name="location_status_check",
        ),
        CheckConstraint(
            "(lat is null) = (lng is null)",
            name="location_coords_paired",
        ),
        Index(
            "ix_location__tenant_fleet",
            "tenant_id",
            "fleet",
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_location__cid",
            "tenant_id",
            "cid",
            postgresql_where=text("cid is not null"),
        ),
    )


class LocationAlias(TenantMixin, Base):
    """Operator-curated former names/domains driving alias-aware discovery.

    No `updated_at` — aliases are appended, not edited in place (`03` §4).
    """

    __tablename__ = "location_alias"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    location_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("location.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("user_profile.id"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint("location_id", "kind", "value"),
        CheckConstraint("kind in ('name','domain')", name="location_alias_kind_check"),
    )
