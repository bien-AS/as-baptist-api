"""Tenant-spine SQLAlchemy models."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TenantMixin, TimestampMixin


class ActorRole(StrEnum):
    """Roles shared by memberships and audit records."""

    as_admin = "as_admin"
    as_staff = "as_staff"
    client_admin = "client_admin"
    client_user = "client_user"
    system = "system"


actor_role_type = ENUM(
    ActorRole,
    name="actor_role",
    create_type=False,
    validate_strings=True,
)


class Tenant(TimestampMixin, Base):
    """A soft-deletable workspace boundary."""

    __tablename__ = "tenant"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="agency_client",
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "tier in ('baptist','agency_client','retail_whitelabel')",
            name="tenant_tier_check",
        ),
        CheckConstraint(
            "status in ('active','suspended','archived')",
            name="tenant_status_check",
        ),
    )


class UserProfile(TimestampMixin, Base):
    """A profile mirrored from the external auth user identity."""

    __tablename__ = "user_profile"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False, unique=True)
    full_name: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(TenantMixin, TimestampMixin, Base):
    """A user's role within a tenant."""

    __tablename__ = "membership"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("user_profile.id"),
        nullable=False,
    )
    role: Mapped[ActorRole] = mapped_column(actor_role_type, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    invited_by: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("user_profile.id"),
    )
    invite_token: Mapped[str | None] = mapped_column(Text, unique=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint(
            "status in ('active','pending','revoked')",
            name="membership_status_check",
        ),
        Index(
            "ix_membership__user",
            "user_id",
            postgresql_where=text("status = 'active'"),
        ),
    )


class MembershipLocation(Base):
    """Optional location scope; the location FK arrives with migration 0003."""

    __tablename__ = "membership_location"

    membership_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("membership.id", ondelete="CASCADE"),
        primary_key=True,
    )
    location_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)


class TenantCredential(TenantMixin, TimestampMixin, Base):
    """A pointer to an external secret; never the provider secret itself."""

    __tablename__ = "tenant_credential"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)
    oauth_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider"),
        CheckConstraint(
            "kind in ('api_key','basic','oauth')",
            name="tenant_credential_kind_check",
        ),
        CheckConstraint(
            "status in ('active','expired','revoked')",
            name="tenant_credential_status_check",
        ),
    )
