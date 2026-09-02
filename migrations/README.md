# Alembic migrations

Migrations run through the separate `MIGRATIONS_DATABASE_URL` connection. The
running API uses `DATABASE_URL` with the restricted `app_api` role instead.
