-- Runs once on first container start (docker-entrypoint-initdb.d).
-- The migration role (POSTGRES_USER) owns the schema. The runtime role below cannot
-- bypass row-level security. Migration 0002 grants it table privileges.
CREATE ROLE concierge_app LOGIN PASSWORD 'concierge_app'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE DATABASE concierge_test OWNER concierge;
