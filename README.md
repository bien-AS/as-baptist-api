# Baptist API

FastAPI foundation for the Baptist GBP platform. This repository is currently
scoped to the platform seams: authentication boundary, tenant spine, async
PostgreSQL runtime, Alembic, and the RLS isolation gate. Product domains such
as locations, reviews, costs, and scans are intentionally deferred until the
tenant-spine gate is proven.

## Development workflow

The repository uses CPython 3.12, a local `.venv`, and `python -m pip`.
`uv` is not part of the repository workflow, and no lockfile or requirements
file is maintained. The globally installed `uv` command is irrelevant here.

On Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The checked-in `.env.example` contains local defaults. Copy it to `.env` for
host commands; never commit `.env` or credentials.

Useful commands:

```text
make dev        # run the API with reload
make test       # run unit tests and configured integration tests
make migrate    # alembic upgrade head through MIGRATIONS_DATABASE_URL
make lint       # Ruff
make typecheck  # strict mypy
```

If GNU Make is unavailable, run the command after the `#` with the active
virtual environment. Docker Desktop is required for the local PostgreSQL
stack:

```text
docker compose up --build
```

The compose API uses `app_api` for runtime traffic and `app_migrator` only for
the local migration command run during container startup. The seed data is
deterministic and contains one local tenant plus test identities:

```text
docker compose exec -T db psql -U postgres -d baptist < sql/seed/local.sql
```

## Configuration

All settings are typed in `app/config.py` and use the following environment
variables:

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `local`, `test`, `staging`, or `production` |
| `DATABASE_URL` | Direct `postgresql+asyncpg` URL used by `app_api` |
| `MIGRATIONS_DATABASE_URL` | Separate URL used only by Alembic/migrations |
| `CORS_ORIGINS` | Comma-separated browser origins |
| `AUTH_MODE` | `mock` locally or `supabase` in deployed environments |
| `SUPABASE_JWKS_URL` | JWKS endpoint required outside local/test |
| `SUPABASE_JWT_AUDIENCE` | JWT audience required outside local/test |
| `SUPABASE_JWT_ISSUER` | JWT issuer required outside local/test |
| `LOG_LEVEL`, `HOST`, `PORT` | Process logging and listener settings |

Production/staging app construction fails if deployed database or Supabase
JWT settings are missing. Local mock auth uses the `dev-token` bearer token
without cloud credentials.

## Database roles and migrations

Alembic migrations use `MIGRATIONS_DATABASE_URL`; the running API must use the
RLS-enforced `app_api` role over direct PostgreSQL port 5432. The pool is
configured with `pool_size=10`, `max_overflow=5`, and `pool_pre_ping=True`.

The initial migrations are:

1. `0001` — `tenant`, `user_profile`, `membership`, `membership_location`, and
   `tenant_credential`.
2. `0002` — role/function scaffolding and the enforced tenant-spine RLS
   policies.

`app_migrator` is the DDL/migration identity. `app_api` has DML only;
`app_worker` has a narrower surface and cannot read identity tables; and
`app_readonly` is read-only. Provider secrets are never stored in the
database—`tenant_credential.secret_ref` is only a secret-store reference.

`app/db/rls.py` is the only permitted location for transaction-local
`set_config` calls. Every tenant-scoped query must run inside
`tenant_context(...)`; isolation is enforced in PostgreSQL rather than by
Python-side `tenant_id` filters.

## Quality gates

CI installs this same pip project, runs Ruff, strict mypy, migration
upgrade/downgrade/upgrade, the coverage suite, architecture/secret checks,
and a production Docker build. The RLS suite was deliberately committed in
two steps: `test(db): add red RLS isolation gate` followed by
`fix(db): enforce RLS policies and pass isolation gate`.

The current host does not include Docker Desktop or GNU Make, so the
PostgreSQL integration suite and container build must run in CI or on a host
with those prerequisites installed.
