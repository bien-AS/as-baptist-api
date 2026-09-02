-- Development-only roles. Production credentials must come from the secret store.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_migrator') THEN
    CREATE ROLE app_migrator LOGIN PASSWORD 'change-me' SUPERUSER CREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_api') THEN
    CREATE ROLE app_api LOGIN PASSWORD 'change-me' NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_worker') THEN
    CREATE ROLE app_worker LOGIN PASSWORD 'change-me' NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_readonly') THEN
    CREATE ROLE app_readonly LOGIN PASSWORD 'change-me' NOSUPERUSER NOBYPASSRLS;
  END IF;
END
$$;

ALTER ROLE app_migrator PASSWORD 'change-me';
ALTER ROLE app_api PASSWORD 'change-me';
ALTER ROLE app_worker PASSWORD 'change-me';
ALTER ROLE app_readonly PASSWORD 'change-me';

GRANT CONNECT ON DATABASE baptist TO app_api, app_worker, app_readonly, app_migrator;
