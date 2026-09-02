"""Database roles and tenant context functions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # asyncpg prepares each op.execute call, so every call below contains one
    # PostgreSQL statement. PL/pgSQL bodies are single statements despite
    # containing their own internal semicolons.
    op.execute("create schema if not exists app")
    op.execute(
        """
        do $$
        begin
          if not exists (select from pg_roles where rolname = 'app_migrator') then
            create role app_migrator noinherit login;
          end if;
          if not exists (select from pg_roles where rolname = 'app_api') then
            create role app_api noinherit login;
          end if;
          if not exists (select from pg_roles where rolname = 'app_worker') then
            create role app_worker noinherit login;
          end if;
          if not exists (select from pg_roles where rolname = 'app_readonly') then
            create role app_readonly noinherit login;
          end if;
        end
        $$
        """
    )
    for statement in (
        "alter role app_api noinherit nosuperuser nobypassrls",
        "alter role app_worker noinherit nosuperuser nobypassrls",
        "alter role app_readonly noinherit nosuperuser nobypassrls",
        "revoke all on schema public from public",
        "grant usage on schema public to app_api, app_worker, app_readonly",
        """
        grant select, insert, update, delete
          on tenant, user_profile, membership, membership_location, tenant_credential
          to app_api
        """,
        "grant select on all tables in schema public to app_worker, app_readonly",
        """
        revoke all on user_profile, membership, membership_location, tenant_credential
          from app_worker
        """,
        "grant select on all tables in schema public to app_readonly",
        """
        alter default privileges in schema public
          grant select, insert, update, delete on tables to app_api
        """,
        """
        alter default privileges in schema public
          grant select on tables to app_worker, app_readonly
        """,
    ):
        op.execute(statement)

    op.execute(
        """
        create or replace function app.current_tenant_id() returns uuid
        language sql stable parallel safe as $$
          select nullif(current_setting('app.tenant_id', true), '')::uuid
        $$
        """
    )
    op.execute(
        """
        create or replace function app.current_actor_id() returns uuid
        language sql stable parallel safe as $$
          select nullif(current_setting('app.actor_id', true), '')::uuid
        $$
        """
    )
    op.execute(
        """
        create or replace function app.current_role() returns text
        language sql stable parallel safe as $$
          select coalesce(nullif(current_setting('app.role', true), ''), 'none')
        $$
        """
    )
    op.execute(
        """
        create or replace function app.is_operator() returns boolean
        language sql stable parallel safe as $$
          select app.current_role() in ('as_admin', 'as_staff', 'system')
        $$
        """
    )
    op.execute(
        """
        create or replace function app.can_read_location(loc uuid) returns boolean
        language sql stable as $$
          select
            case
              when app.is_operator() then true
              when not exists (
                select 1 from membership m
                join membership_location ml on ml.membership_id = m.id
                where m.tenant_id = app.current_tenant_id()
                  and m.user_id = app.current_actor_id()
                  and m.status = 'active'
              ) then true
              else exists (
                select 1 from membership m
                join membership_location ml on ml.membership_id = m.id
                where m.tenant_id = app.current_tenant_id()
                  and m.user_id = app.current_actor_id()
                  and m.status = 'active'
                  and ml.location_id = loc
              )
            end
        $$
        """
    )
    op.execute(
        """
        create or replace function app.tg_enforce_tenant() returns trigger
        language plpgsql as $$
        begin
          if current_user = 'app_migrator' then
            return new;
          end if;
          if app.current_tenant_id() is null then
            raise exception 'no tenant bound: refusing write to %', tg_table_name
              using errcode = '42501';
          end if;
          if tg_op = 'INSERT' then
            if new.tenant_id is null then
              new.tenant_id := app.current_tenant_id();
            elsif new.tenant_id <> app.current_tenant_id() then
              raise exception 'cross-tenant insert blocked on %', tg_table_name
                using errcode = '42501';
            end if;
          elsif tg_op = 'UPDATE' and new.tenant_id <> old.tenant_id then
            raise exception 'tenant_id is immutable on %', tg_table_name
              using errcode = '42501';
          end if;
          return new;
        end
        $$
        """
    )
    op.execute(
        """
        create or replace function app.tg_set_updated_at() returns trigger
        language plpgsql as $$
        begin
          new.updated_at := now();
          return new;
        end
        $$
        """
    )
    for statement in (
        "grant usage on schema app to app_api, app_worker, app_readonly",
        "grant execute on function app.current_tenant_id() to app_api, app_worker, app_readonly",
        "grant execute on function app.current_actor_id() to app_api, app_worker, app_readonly",
        "grant execute on function app.current_role() to app_api, app_worker, app_readonly",
        "grant execute on function app.is_operator() to app_api, app_worker, app_readonly",
        "grant execute on function app.can_read_location(uuid) "
        "to app_api, app_worker, app_readonly",
    ):
        op.execute(statement)

    for table in (
        "tenant",
        "user_profile",
        "membership",
        "membership_location",
        "tenant_credential",
    ):
        op.execute(f"alter table {table} enable row level security")
        op.execute(f"alter table {table} force row level security")

    for statement in (
        """
        create policy tenant_context_select on tenant
          for select to app_api, app_worker, app_readonly
          using (id = app.current_tenant_id())
        """,
        """
        create policy user_profile_self on user_profile
          for select to app_api
          using (id = app.current_actor_id())
        """,
        """
        create policy membership_select_tenant on membership
          for select to app_api, app_worker, app_readonly
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy membership_insert_tenant on membership
          for insert to app_api, app_worker
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy membership_update_tenant on membership
          for update to app_api, app_worker
          using (tenant_id = app.current_tenant_id())
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy membership_delete_tenant on membership
          for delete to app_api
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy membership_location_select on membership_location
          for select to app_api, app_worker, app_readonly
          using (exists (
            select 1 from membership m
            where m.id = membership_location.membership_id
              and m.tenant_id = app.current_tenant_id()
          ))
        """,
        """
        create policy membership_location_insert on membership_location
          for insert to app_api, app_worker
          with check (exists (
            select 1 from membership m
            where m.id = membership_location.membership_id
              and m.tenant_id = app.current_tenant_id()
          ))
        """,
        """
        create policy membership_location_update on membership_location
          for update to app_api, app_worker
          using (exists (
            select 1 from membership m
            where m.id = membership_location.membership_id
              and m.tenant_id = app.current_tenant_id()
          ))
          with check (exists (
            select 1 from membership m
            where m.id = membership_location.membership_id
              and m.tenant_id = app.current_tenant_id()
          ))
        """,
        """
        create policy membership_location_delete on membership_location
          for delete to app_api
          using (exists (
            select 1 from membership m
            where m.id = membership_location.membership_id
              and m.tenant_id = app.current_tenant_id()
          ))
        """,
        """
        create policy tenant_credential_select_tenant on tenant_credential
          for select to app_api
          using (tenant_id = app.current_tenant_id())
        """,
        """
        create policy tenant_credential_insert_tenant on tenant_credential
          for insert to app_api, app_worker
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy tenant_credential_update_tenant on tenant_credential
          for update to app_api, app_worker
          using (tenant_id = app.current_tenant_id())
          with check (tenant_id = app.current_tenant_id())
        """,
        """
        create policy tenant_credential_delete_tenant on tenant_credential
          for delete to app_api
          using (tenant_id = app.current_tenant_id())
        """,
    ):
        op.execute(statement)

    for statement in (
        """
        create trigger trg_membership_enforce_tenant
          before insert or update on membership
          for each row execute function app.tg_enforce_tenant()
        """,
        """
        create trigger trg_tenant_credential_enforce_tenant
          before insert or update on tenant_credential
          for each row execute function app.tg_enforce_tenant()
        """,
        """
        create trigger trg_tenant_updated_at
          before update on tenant
          for each row execute function app.tg_set_updated_at()
        """,
        """
        create trigger trg_user_profile_updated_at
          before update on user_profile
          for each row execute function app.tg_set_updated_at()
        """,
        """
        create trigger trg_membership_updated_at
          before update on membership
          for each row execute function app.tg_set_updated_at()
        """,
        """
        create trigger trg_tenant_credential_updated_at
          before update on tenant_credential
          for each row execute function app.tg_set_updated_at()
        """,
    ):
        op.execute(statement)


def downgrade() -> None:
    for statement in (
        "drop trigger if exists trg_membership_enforce_tenant on membership",
        "drop trigger if exists trg_tenant_credential_enforce_tenant on tenant_credential",
        "drop trigger if exists trg_tenant_updated_at on tenant",
        "drop trigger if exists trg_user_profile_updated_at on user_profile",
        "drop trigger if exists trg_membership_updated_at on membership",
        "drop trigger if exists trg_tenant_credential_updated_at on tenant_credential",
        "drop policy if exists tenant_context_select on tenant",
        "drop policy if exists user_profile_self on user_profile",
        "drop policy if exists membership_select_tenant on membership",
        "drop policy if exists membership_insert_tenant on membership",
        "drop policy if exists membership_update_tenant on membership",
        "drop policy if exists membership_delete_tenant on membership",
        "drop policy if exists membership_location_select on membership_location",
        "drop policy if exists membership_location_insert on membership_location",
        "drop policy if exists membership_location_update on membership_location",
        "drop policy if exists membership_location_delete on membership_location",
        "drop policy if exists tenant_credential_select_tenant on tenant_credential",
        "drop policy if exists tenant_credential_insert_tenant on tenant_credential",
        "drop policy if exists tenant_credential_update_tenant on tenant_credential",
        "drop policy if exists tenant_credential_delete_tenant on tenant_credential",
    ):
        op.execute(statement)

    for table in (
        "tenant",
        "user_profile",
        "membership",
        "membership_location",
        "tenant_credential",
    ):
        op.execute(f"alter table {table} no force row level security")
        op.execute(f"alter table {table} disable row level security")

    op.execute("drop schema if exists app cascade")
