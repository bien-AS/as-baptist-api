"""Audit card, cost ledger, cost budget, and the write_card/assert_budget functions.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

ACTOR_ROLE = ("as_admin", "as_staff", "client_admin", "client_user", "system")
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
    actor_role = postgresql.ENUM(*ACTOR_ROLE, name="actor_role", create_type=False)
    data_source = postgresql.ENUM(*DATA_SOURCE, name="data_source", create_type=False)

    op.create_table(
        "audit_card",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "occurred_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_label", sa.Text(), nullable=False),
        sa.Column("actor_role", actor_role, nullable=False),
        sa.Column("verb", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text()),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True)),
        sa.Column("request_id", sa.Text()),
        sa.Column("detail", postgresql.JSONB()),
        sa.Column(
            "simulated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "source",
            data_source,
            server_default="computed",
            nullable=False,
        ),
        sa.CheckConstraint(
            "verb in ('create','update','delete','approve','reject','read','execute')",
            name="audit_card_verb_check",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["user_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_card__tenant_time",
        "audit_card",
        ["tenant_id", sa.text("occurred_at desc")],
    )
    op.create_index(
        "ix_audit_card__resource",
        "audit_card",
        ["tenant_id", "resource_type", "resource_id"],
    )
    op.create_index(
        "ix_audit_card__location",
        "audit_card",
        ["tenant_id", "location_id", sa.text("occurred_at desc")],
    )

    op.create_table(
        "cost_ledger",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "occurred_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "billing_date",
            sa.Date(),
            server_default=sa.text("current_date"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("unit_cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 4), nullable=False),
        sa.Column("billing", sa.Text(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True)),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("source", data_source, nullable=False),
        sa.CheckConstraint("units >= 0", name="cost_ledger_units_check"),
        sa.CheckConstraint(
            "billing in ('billed','plan_credits','projected')",
            name="cost_ledger_billing_check",
        ),
        sa.CheckConstraint(
            "round(units * unit_cost_usd, 4) = cost_usd or billing = 'plan_credits'",
            name="cost_ledger_math",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cost_ledger__tenant_period",
        "cost_ledger",
        ["tenant_id", sa.text("billing_date desc")],
    )
    op.create_index(
        "ix_cost_ledger__provider",
        "cost_ledger",
        ["tenant_id", "provider", sa.text("billing_date desc")],
    )

    op.create_table(
        "cost_budget",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("monthly_cap_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("per_run_cap_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "balance_floor_usd",
            sa.Numeric(12, 2),
            server_default="100.00",
            nullable=False,
        ),
        sa.Column(
            "hard_stop",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "period_month"),
    )

    # ── RLS ────────────────────────────────────────────────────────────────
    for table in ("audit_card", "cost_ledger", "cost_budget"):
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")

    for statement in (
        # audit_card: reads are the standard tenant policy; INSERT is worker-only
        # (app_api writes exclusively through audit.write_card() below). No
        # UPDATE/DELETE policy exists — nothing holds that grant, and
        # trg_audit_card_immutable refuses it unconditionally regardless.
        """
        create policy audit_card_select_tenant on audit_card
          for select to app_api, app_worker, app_readonly
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy audit_card_insert_worker on audit_card
          for insert to app_worker
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy cost_ledger_select_tenant on cost_ledger
          for select to app_api, app_worker, app_readonly
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy cost_ledger_insert_tenant on cost_ledger
          for insert to app_api, app_worker
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy cost_ledger_update_tenant on cost_ledger
          for update to app_api
          using (tenant_id = app.current_tenant_id())
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy cost_ledger_delete_tenant on cost_ledger
          for delete to app_api
          using (tenant_id = app.current_tenant_id())
        """,
        # cost_budget: app_worker has no grant at all here (see revokes below).
        """
        create policy cost_budget_select_tenant on cost_budget
          for select to app_api, app_readonly
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy cost_budget_insert_tenant on cost_budget
          for insert to app_api
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy cost_budget_update_tenant on cost_budget
          for update to app_api
          using (tenant_id = app.current_tenant_id())
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy cost_budget_delete_tenant on cost_budget
          for delete to app_api
          using (tenant_id = app.current_tenant_id())
        """,
    ):
        op.execute(statement)

    for statement in (
        """
        create trigger trg_audit_card_enforce_tenant
          before insert or update on audit_card
          for each row execute function app.tg_enforce_tenant()
        """,
        """
        create trigger trg_cost_ledger_enforce_tenant
          before insert or update on cost_ledger
          for each row execute function app.tg_enforce_tenant()
        """,
        """
        create trigger trg_cost_budget_enforce_tenant
          before insert or update on cost_budget
          for each row execute function app.tg_enforce_tenant()
        """,
        """
        create trigger trg_cost_budget_updated_at
          before update on cost_budget
          for each row execute function app.tg_set_updated_at()
        """,
    ):
        op.execute(statement)

    # ── Grants: default privileges already gave app_api full CRUD and
    # app_worker/app_readonly SELECT on these new tables (migration 0002).
    # Narrow them to match 04 §2 and BE-06's pass criteria exactly. ─────────
    for statement in (
        # Append-only: not even app_api may write audit_card directly.
        "revoke insert, update, delete on audit_card from app_api",
        "grant insert on audit_card to app_worker",
        "grant insert on cost_ledger to app_worker",
        "revoke all on cost_budget from app_worker",
    ):
        op.execute(statement)

    # ── Functions (04 §5.3-5.4) ──────────────────────────────────────────
    op.execute("create schema if not exists audit")
    op.execute(
        """
        create or replace function audit.tg_forbid_mutation() returns trigger
        language plpgsql as $$
        begin
          raise exception 'audit_card is append-only (attempted %)', tg_op
            using errcode = '42501';
        end
        $$
        """
    )
    op.execute(
        """
        create trigger trg_audit_card_immutable
          before update or delete on audit_card
          for each row execute function audit.tg_forbid_mutation()
        """
    )
    op.execute(
        """
        create or replace function audit.write_card(
          p_location_id   uuid,
          p_verb          text,
          p_action        text,
          p_resource_type text,
          p_resource_id   text    default null,
          p_approval_id   uuid    default null,
          p_detail        jsonb   default null,
          p_simulated     boolean default false
        ) returns bigint
        language plpgsql security definer set search_path = public, pg_temp as $$
        declare v_id bigint; v_label text;
        begin
          if app.current_tenant_id() is null then
            raise exception 'no tenant bound: refusing audit write' using errcode = '42501';
          end if;
          select coalesce(full_name, email::text) into v_label
            from user_profile where id = app.current_actor_id();

          insert into audit_card (tenant_id, location_id, actor_id, actor_label, actor_role,
                                  verb, action, resource_type, resource_id, approval_id,
                                  detail, simulated, request_id)
          values (app.current_tenant_id(), p_location_id, app.current_actor_id(),
                  coalesce(v_label, 'system'), app.current_role()::actor_role,
                  p_verb, p_action, p_resource_type, p_resource_id, p_approval_id,
                  p_detail, p_simulated,
                  nullif(current_setting('app.request_id', true), ''))
          returning id into v_id;
          return v_id;
        end
        $$
        """
    )
    for statement in (
        "revoke all on function audit.write_card"
        "(uuid, text, text, text, text, uuid, jsonb, boolean) from public",
        "grant execute on function audit.write_card"
        "(uuid, text, text, text, text, uuid, jsonb, boolean) to app_api, app_worker",
    ):
        op.execute(statement)

    op.execute("create schema if not exists cost")
    op.execute(
        """
        create or replace function cost.month_spend(
          p_month date default date_trunc('month', current_date)::date
        )
        returns numeric language sql stable as $$
          select coalesce(sum(cost_usd), 0)
          from cost_ledger
          where tenant_id = app.current_tenant_id()
            and billing = 'billed'
            and billing_date >= p_month
            and billing_date <  (p_month + interval '1 month')::date
        $$
        """
    )
    op.execute(
        """
        create or replace function cost.assert_budget(
          p_projected_usd numeric, p_balance_usd numeric default null
        )
        returns void language plpgsql stable as $$
        declare b record; v_spent numeric;
        begin
          select * into b from cost_budget
           where tenant_id = app.current_tenant_id()
             and period_month = date_trunc('month', current_date)::date;

          if not found then
            raise exception 'no cost budget configured for this tenant/month'
              using errcode = 'P0001', hint = 'insert a cost_budget row before spending';
          end if;

          if p_projected_usd > b.per_run_cap_usd then
            raise exception 'run cost %.2f exceeds per-run cap %.2f',
              p_projected_usd, b.per_run_cap_usd using errcode = 'P0001';
          end if;

          v_spent := cost.month_spend();
          if b.hard_stop and (v_spent + p_projected_usd) > b.monthly_cap_usd then
            raise exception 'monthly cap exceeded: spent %.2f + projected %.2f > cap %.2f',
              v_spent, p_projected_usd, b.monthly_cap_usd using errcode = 'P0001';
          end if;

          if p_balance_usd is not null
             and (p_balance_usd - p_projected_usd) < b.balance_floor_usd then
            raise exception 'provider balance %.2f would fall below floor %.2f',
              p_balance_usd, b.balance_floor_usd using errcode = 'P0001';
          end if;
        end
        $$
        """
    )
    for statement in (
        "grant usage on schema audit, cost to app_api, app_worker",
        "grant execute on function cost.month_spend(date) to app_api, app_worker",
        "grant execute on function cost.assert_budget(numeric, numeric) to app_api, app_worker",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("drop function if exists cost.assert_budget(numeric, numeric)")
    op.execute("drop function if exists cost.month_spend(date)")
    op.execute("drop schema if exists cost cascade")

    op.execute(
        "drop function if exists audit.write_card"
        "(uuid, text, text, text, text, uuid, jsonb, boolean)"
    )
    op.execute("drop trigger if exists trg_audit_card_immutable on audit_card")
    op.execute("drop function if exists audit.tg_forbid_mutation()")
    op.execute("drop schema if exists audit cascade")

    for statement in (
        "drop trigger if exists trg_audit_card_enforce_tenant on audit_card",
        "drop trigger if exists trg_cost_ledger_enforce_tenant on cost_ledger",
        "drop trigger if exists trg_cost_budget_enforce_tenant on cost_budget",
        "drop trigger if exists trg_cost_budget_updated_at on cost_budget",
        "drop policy if exists audit_card_select_tenant on audit_card",
        "drop policy if exists audit_card_insert_worker on audit_card",
        "drop policy if exists cost_ledger_select_tenant on cost_ledger",
        "drop policy if exists cost_ledger_insert_tenant on cost_ledger",
        "drop policy if exists cost_ledger_update_tenant on cost_ledger",
        "drop policy if exists cost_ledger_delete_tenant on cost_ledger",
        "drop policy if exists cost_budget_select_tenant on cost_budget",
        "drop policy if exists cost_budget_insert_tenant on cost_budget",
        "drop policy if exists cost_budget_update_tenant on cost_budget",
        "drop policy if exists cost_budget_delete_tenant on cost_budget",
    ):
        op.execute(statement)

    op.drop_table("cost_budget")
    op.drop_index("ix_cost_ledger__provider", table_name="cost_ledger")
    op.drop_index("ix_cost_ledger__tenant_period", table_name="cost_ledger")
    op.drop_table("cost_ledger")
    op.drop_index("ix_audit_card__location", table_name="audit_card")
    op.drop_index("ix_audit_card__resource", table_name="audit_card")
    op.drop_index("ix_audit_card__tenant_time", table_name="audit_card")
    op.drop_table("audit_card")
