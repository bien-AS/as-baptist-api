# Local API setup

This workflow runs PostgreSQL in Docker and runs the FastAPI process directly
from the Python 3.12 virtual environment. Uvicorn watches the source tree and
restarts the development server when Python files change. The API is not a
service in `docker-compose.local.yml`.

Supabase is not required for local development. Local authentication uses the
mock verifier; Supabase remains the deployed JWT/JWKS authentication boundary.

## Prerequisites

- Docker Desktop running
- CPython 3.12 available as `py -3.12`
- PowerShell from the repository directory: `C:\baptist\api`

## One-time Python setup

```powershell
Set-Location C:\baptist\api
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

If PowerShell activation is unavailable, use the interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The virtual environment is ignored by Git. Do not commit `.env` or any file
containing real credentials.

## Environment

`app/config.py` loads `.env` automatically. Process environment variables take
precedence over the file. The checked-in `.env.example` has safe local values:

```dotenv
APP_ENV=local
AUTH_MODE=mock
DATABASE_URL=postgresql+asyncpg://app_api:change-me@localhost:5432/baptist
MIGRATIONS_DATABASE_URL=postgresql+asyncpg://app_migrator:change-me@localhost:5432/baptist
CORS_ORIGINS=http://localhost:5173
```

For the host-run API, use `localhost` in both database URLs. The `db` hostname
is only available to containers on the Compose network. `LOG_LEVEL`, `HOST`,
and `PORT` are optional local settings; the Uvicorn command below supplies the
development listener explicitly.

Local mock-auth defaults are `dev-token`, the seeded local admin user, and the
`baptist-local` tenant. The `SUPABASE_JWKS_URL`, audience, and issuer settings
can remain empty locally. Staging and production require `AUTH_MODE=supabase`,
`SUPABASE_JWKS_URL`, `SUPABASE_JWT_AUDIENCE`, and `SUPABASE_JWT_ISSUER`.

## Start PostgreSQL only

Use the local Compose file from the repository directory. It defines only the
database service, so it does not start or build the API:

```powershell
docker compose -f docker-compose.local.yml up -d
docker compose -f docker-compose.local.yml ps
```

Wait for the database to report `healthy` before migrating. The database is
published on `localhost:5432`, and its named volume is preserved by normal
`down` commands.

## Apply migrations and seed data

Run Alembic from the activated virtual environment. It uses
`MIGRATIONS_DATABASE_URL`, which must point to `app_migrator`, never
`app_api`:

```powershell
python -m alembic upgrade head
python -m alembic current
```

Seed the deterministic local tenant and test identities with the migrator
role:

```powershell
Get-Content sql/seed/local.sql | docker compose -f docker-compose.local.yml exec -T db psql -U app_migrator -d baptist
```

The seed is idempotent. To verify the local database directly:

```powershell
docker compose -f docker-compose.local.yml exec -T db psql -U app_migrator -d baptist -c "select version_num from alembic_version;"
```

## Run the API with automatic reload

Keep PostgreSQL running in one terminal and start the API in another:

```powershell
Set-Location C:\baptist\api
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Uvicorn watches the current project directory and restarts the process when
source files change. The API is available at `http://127.0.0.1:8000`.

Basic checks:

```powershell
curl.exe http://127.0.0.1:8000/v1/health
curl.exe http://127.0.0.1:8000/v1/ready
```

`/v1/health` does not require PostgreSQL. `/v1/ready` returns `200` only when
the local database is reachable and returns an RFC 9457 `503` problem when it
is unavailable.

The equivalent Make target is `make dev` when GNU Make is installed:

```text
make dev
```

## Run quality checks

The live RLS suite needs all three role URLs in the current shell. These are
test-only variables; pytest reads them from the process environment rather
than from Pydantic's `.env` settings loader:

```powershell
$env:TEST_API_DATABASE_URL = "postgresql+asyncpg://app_api:change-me@127.0.0.1:5432/baptist"
$env:TEST_MIGRATIONS_DATABASE_URL = "postgresql+asyncpg://app_migrator:change-me@127.0.0.1:5432/baptist"
$env:TEST_WORKER_DATABASE_URL = "postgresql+asyncpg://app_worker:change-me@127.0.0.1:5432/baptist"

python -m ruff check app migrations tests scripts
python -m mypy app
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=70
```

## Stop the local environment

Stop the host API with `Ctrl+C`, then stop PostgreSQL:

```powershell
docker compose -f docker-compose.local.yml down
```

Normal `down` preserves the database volume. Do not add `-v` unless you
intentionally want to delete the local database and recreate it.

The full containerized stack remains available separately through
`docker compose up --build`; that command starts both the API and PostgreSQL.

