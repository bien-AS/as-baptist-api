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
    op.execute(
        """
        create schema if not exists app;

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
        $$;

        alter role app_api noinherit nosuperuser nobypassrls;
        alter role app_worker noinherit nosuperuser nobypassrls;
        alter role app_readonly noinherit nosuperuser nobypassrls;

        revoke all on schema public from public;
        grant usage on schema public to app_api, app_worker, app_readonly;

        grant select, insert, update, delete
          on tenant, user_profile, membership, membership_location, tenant_credential
          to app_api;
        grant select on all tables in schema public to app_worker, app_readonly;
        revoke all on user_profile, membership, tenant_credential from app_worker;
        grant select on all tables in schema public to app_readonly;

        alter default privileges in schema public
          grant select, insert, update, delete on tables to app_api;
        alter default privileges in schema public
          grant select on tables to app_worker, app_readonly;
        """
    )
    op.execute(
        """
        create or replace function app.current_tenant_id() returns uuid
        language sql stable parallel safe as $$
          select nullif(current_setting('app.tenant_id', true), '')::uuid
        $$;

        create or replace function app.current_actor_id() returns uuid
        language sql stable parallel safe as $$
          select nullif(current_setting('app.actor_id', true), '')::uuid
        $$;

        create or replace function app.current_role() returns text
        language sql stable parallel safe as $$
          select coalesce(nullif(current_setting('app.role', true), ''), 'none')
        $$;

        create or replace function app.is_operator() returns boolean
        language sql stable parallel safe as $$
          select app.current_role() in ('as_admin', 'as_staff', 'system')
        $$;

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
        $$;

        create or replace function app.tg_enforce_tenant() returns trigger
        language plpgsql as $$
        begin
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
        $$;

        create or replace function app.tg_set_updated_at() returns trigger
        language plpgsql as $$
        begin
          new.updated_at := now();
          return new;
        end
        $$;

        grant usage on schema app to app_api, app_worker, app_readonly;
        grant execute on function app.current_tenant_id() to app_api, app_worker, app_readonly;
        grant execute on function app.current_actor_id() to app_api, app_worker, app_readonly;
        grant execute on function app.current_role() to app_api, app_worker, app_readonly;
        grant execute on function app.is_operator() to app_api, app_worker, app_readonly;
        grant execute on function app.can_read_location(uuid) to app_api, app_worker, app_readonly;
        """
    )


def downgrade() -> None:
    op.execute("drop schema if exists app cascade")
