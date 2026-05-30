-- Runs once on a fresh postgres volume (docker-entrypoint-initdb.d).
-- Creates the dedicated database for Dagster's run/event/schedule storage so it
-- does not share an alembic_version table with the app. See docker/dagster.dev.yaml.
SELECT 'CREATE DATABASE engrammic_dagster'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'engrammic_dagster')\gexec
