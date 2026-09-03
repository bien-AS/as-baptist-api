"""Cost preview, approval, and the deferred audit_card.approval_id FK.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cost_preview",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True)),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("units", postgresql.JSONB(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 4), nullable=False),
        sa.Column("gates", postgresql.JSONB(), nullable=False),
        sa.Column("passes", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now() + interval '15 minutes'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["user_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "approval",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True)),
        sa.Column("cost_preview_id", postgresql.UUID(as_uuid=True)),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "approved_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="approved", nullable=False),
        sa.Column("executed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("actual_cost_usd", sa.Numeric(12, 4)),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error", postgresql.JSONB()),
        sa.CheckConstraint(
            "status in ('approved','executing','executed','failed','expired')",
            name="approval_status_check",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"]),
        sa.ForeignKeyConstraint(["cost_preview_id"], ["cost_preview.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["user_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key"),
    )

    # Deferred from 0004: audit_card.approval_id had no table to reference yet.
    op.create_foreign_key(
        "fk_audit_card__approval", "audit_card", "approval", ["approval_id"], ["id"]
    )

    for table in ("cost_preview", "approval"):
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")

    for statement in (
        """
        create policy cost_preview_select_tenant on cost_preview
          for select to app_api, app_worker, app_readonly
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy cost_preview_insert_tenant on cost_preview
          for insert to app_api
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy cost_preview_update_tenant on cost_preview
          for update to app_api
          using (tenant_id = app.current_tenant_id())
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy cost_preview_delete_tenant on cost_preview
          for delete to app_api
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy approval_select_tenant on approval
          for select to app_api
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy approval_insert_tenant on approval
          for insert to app_api
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy approval_update_tenant on approval
          for update to app_api
          using (tenant_id = app.current_tenant_id())
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy approval_delete_tenant on approval
          for delete to app_api
          using (tenant_id = app.current_tenant_id())
        """,
    ):
        op.execute(statement)

    op.execute(
        """
        create trigger trg_cost_preview_enforce_tenant
          before insert or update on cost_preview
          for each row execute function app.tg_enforce_tenant()
        """
    )
    op.execute(
        """
        create trigger trg_approval_enforce_tenant
          before insert or update on approval
          for each row execute function app.tg_enforce_tenant()
        """
    )

    # approval is operator-facing only (`04` §2) -- the worker never touches it.
    op.execute("revoke all on approval from app_worker")


def downgrade() -> None:
    op.execute("drop trigger if exists trg_cost_preview_enforce_tenant on cost_preview")
    op.execute("drop trigger if exists trg_approval_enforce_tenant on approval")
    for statement in (
        "drop policy if exists cost_preview_select_tenant on cost_preview",
        "drop policy if exists cost_preview_insert_tenant on cost_preview",
        "drop policy if exists cost_preview_update_tenant on cost_preview",
        "drop policy if exists cost_preview_delete_tenant on cost_preview",
        "drop policy if exists approval_select_tenant on approval",
        "drop policy if exists approval_insert_tenant on approval",
        "drop policy if exists approval_update_tenant on approval",
        "drop policy if exists approval_delete_tenant on approval",
    ):
        op.execute(statement)

    op.drop_constraint("fk_audit_card__approval", "audit_card", type_="foreignkey")
    op.drop_table("approval")
    op.drop_table("cost_preview")
