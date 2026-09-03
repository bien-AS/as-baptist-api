"""Location domain tables, location-scoped RLS, and the deferred membership FK.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

FLEET_KIND = ("hospital", "clinic")
LISTING_TYPE = ("facility", "department", "practitioner")
DATA_SOURCE = (
    "searchatlas",
    "dataforseo",
    "serper",
    "brightlocal",
    "synthetic",
    "computed",
    "client_verified",
)


def upgrade() -> None:
    fleet_kind = postgresql.ENUM(*FLEET_KIND, name="fleet_kind", create_type=False)
    listing_type = postgresql.ENUM(*LISTING_TYPE, name="listing_type", create_type=False)
    data_source = postgresql.ENUM(*DATA_SOURCE, name="data_source", create_type=False)

    op.create_table(
        "location",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text()),
        sa.Column("fleet", fleet_kind),
        sa.Column("listing_type", listing_type, nullable=False),
        sa.Column("facility_type", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("state", sa.CHAR(2), nullable=False),
        sa.Column("zip", sa.Text(), nullable=False),
        sa.Column("lat", sa.Numeric(10, 7)),
        sa.Column("lng", sa.Numeric(10, 7)),
        sa.Column("place_id", sa.Text()),
        sa.Column("cid", sa.Text()),
        sa.Column("phone", sa.Text()),
        sa.Column("website", sa.Text()),
        sa.Column("domain", sa.Text()),
        sa.Column("primary_category", sa.Text()),
        sa.Column(
            "additional_categories",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("is_claimed", sa.Boolean()),
        sa.Column("is_verified", sa.Boolean()),
        sa.Column("total_photos", sa.Integer()),
        sa.Column("rating_value", sa.Numeric(2, 1)),
        sa.Column("rating_votes", sa.Integer()),
        sa.Column("rating_distribution", postgresql.JSONB()),
        sa.Column("work_time", postgresql.JSONB()),
        sa.Column("attributes", postgresql.JSONB()),
        sa.Column("place_topics", postgresql.JSONB()),
        sa.Column("searchatlas_business_id", sa.Integer()),
        sa.Column("searchatlas_audit_report_id", sa.Integer()),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column(
            "enriched",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("source", data_source, nullable=False),
        sa.Column("fetched_at", sa.TIMESTAMP(timezone=True)),
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
            "status in ('active','onboarding','paused','archived')",
            name="location_status_check",
        ),
        sa.CheckConstraint("(lat is null) = (lng is null)", name="location_coords_paired"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug"),
    )
    op.create_index(
        "ix_location__tenant_fleet",
        "location",
        ["tenant_id", "fleet"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_location__cid",
        "location",
        ["tenant_id", "cid"],
        postgresql_where=sa.text("cid is not null"),
    )

    op.create_table(
        "location_alias",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind in ('name','domain')", name="location_alias_kind_check"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("location_id", "kind", "value"),
    )

    # Deferred from 0001: membership_location.location_id had no table to reference yet.
    op.create_foreign_key(
        "fk_membership_location__location",
        "membership_location",
        "location",
        ["location_id"],
        ["id"],
        ondelete="CASCADE",
    )

    for table in ("location", "location_alias"):
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")

    for statement in (
        # app_api reads through the location-scope function (04 §3.6); app_worker and
        # app_readonly are not user-facing and keep the plain tenant policy instead.
        """
        create policy location_select_scoped on location
          for select to app_api
          using (tenant_id = app.current_tenant_id() and app.can_read_location(id))
        """,
        """
        create policy location_select_tenant on location
          for select to app_worker, app_readonly
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy location_insert_tenant on location
          for insert to app_api
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy location_update_tenant on location
          for update to app_api
          using (tenant_id = app.current_tenant_id())
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy location_delete_tenant on location
          for delete to app_api
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy location_alias_select_tenant on location_alias
          for select to app_api, app_worker, app_readonly
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy location_alias_insert_tenant on location_alias
          for insert to app_api, app_worker
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy location_alias_update_tenant on location_alias
          for update to app_api, app_worker
          using (tenant_id = app.current_tenant_id())
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy location_alias_delete_tenant on location_alias
          for delete to app_api
          using (tenant_id = app.current_tenant_id())
        """,
    ):
        op.execute(statement)

    for statement in (
        """
        create trigger trg_location_enforce_tenant
          before insert or update on location
          for each row execute function app.tg_enforce_tenant()
        """,
        """
        create trigger trg_location_updated_at
          before update on location
          for each row execute function app.tg_set_updated_at()
        """,
        """
        create trigger trg_location_alias_enforce_tenant
          before insert or update on location_alias
          for each row execute function app.tg_enforce_tenant()
        """,
    ):
        op.execute(statement)


def downgrade() -> None:
    for statement in (
        "drop trigger if exists trg_location_enforce_tenant on location",
        "drop trigger if exists trg_location_updated_at on location",
        "drop trigger if exists trg_location_alias_enforce_tenant on location_alias",
        "drop policy if exists location_select_scoped on location",
        "drop policy if exists location_select_tenant on location",
        "drop policy if exists location_insert_tenant on location",
        "drop policy if exists location_update_tenant on location",
        "drop policy if exists location_delete_tenant on location",
        "drop policy if exists location_alias_select_tenant on location_alias",
        "drop policy if exists location_alias_insert_tenant on location_alias",
        "drop policy if exists location_alias_update_tenant on location_alias",
        "drop policy if exists location_alias_delete_tenant on location_alias",
    ):
        op.execute(statement)

    op.drop_constraint(
        "fk_membership_location__location", "membership_location", type_="foreignkey"
    )
    op.drop_table("location_alias")
    op.drop_index("ix_location__cid", table_name="location")
    op.drop_index("ix_location__tenant_fleet", table_name="location")
    op.drop_table("location")
