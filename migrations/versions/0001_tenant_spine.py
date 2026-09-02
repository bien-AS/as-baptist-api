"""Tenant spine tables.

Revision ID: 0001
Revises:
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SHARED_ENUMS = {
    "data_source": (
        "searchatlas",
        "dataforseo",
        "serper",
        "brightlocal",
        "synthetic",
        "computed",
        "client_verified",
    ),
    "listing_type": ("facility", "department", "practitioner"),
    "fleet_kind": ("hospital", "clinic"),
    "layer_type": ("map_pack", "local_finder", "organic", "ai_mode"),
    "device_type": ("desktop", "mobile"),
    "actor_role": ("as_admin", "as_staff", "client_admin", "client_user", "system"),
    "lvi_band": ("elite", "healthy", "at-risk", "critical"),
}


def upgrade() -> None:
    op.execute("create extension if not exists pgcrypto")
    op.execute("create extension if not exists citext")
    bind = op.get_bind()
    for enum_name, enum_values in SHARED_ENUMS.items():
        postgresql.ENUM(*enum_values, name=enum_name).create(bind, checkfirst=True)
    actor_role = postgresql.ENUM(
        *SHARED_ENUMS["actor_role"],
        name="actor_role",
        create_type=False,
    )

    op.create_table(
        "tenant",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), server_default="agency_client", nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True)),
        sa.CheckConstraint(
            "tier in ('baptist','agency_client','retail_whitelabel')",
            name="tenant_tier_check",
        ),
        sa.CheckConstraint(
            "status in ('active','suspended','archived')",
            name="tenant_status_check",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "user_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("full_name", sa.Text()),
        sa.Column("avatar_url", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_active_at", sa.TIMESTAMP(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "membership",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", actor_role, nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True)),
        sa.Column("invite_token", sa.Text()),
        sa.Column("invite_expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("joined_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('active','pending','revoked')",
            name="membership_status_check",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user_profile.id"]),
        sa.ForeignKeyConstraint(["invited_by"], ["user_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invite_token"),
        sa.UniqueConstraint("tenant_id", "user_id"),
    )
    op.create_index(
        "ix_membership__user",
        "membership",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "membership_location",
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["membership_id"], ["membership.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("membership_id", "location_id"),
    )

    op.create_table(
        "tenant_credential",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("secret_ref", sa.Text(), nullable=False),
        sa.Column("oauth_expires_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind in ('api_key','basic','oauth')",
            name="tenant_credential_kind_check",
        ),
        sa.CheckConstraint(
            "status in ('active','expired','revoked')",
            name="tenant_credential_status_check",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "provider"),
    )


def downgrade() -> None:
    op.drop_table("tenant_credential")
    op.drop_table("membership_location")
    op.drop_index("ix_membership__user", table_name="membership")
    op.drop_table("membership")
    op.drop_table("user_profile")
    op.drop_table("tenant")
    for enum_name in reversed(tuple(SHARED_ENUMS)):
        op.execute(f"drop type if exists {enum_name}")
