#!/bin/sh
# Runs once, the first time the database container starts. Creates the unprivileged runtime role
# the API connects as. It cannot bypass row-level security. The owner role (POSTGRES_USER) is only
# used for migrations and the operator CLI.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE concierge_app LOGIN PASSWORD '${APP_DB_PASSWORD}'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
SQL
