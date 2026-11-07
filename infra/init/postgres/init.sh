#!/bin/sh
set -e

# Restricted analyst role creation for PostgreSQL fixture
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE analyst_read LOGIN PASSWORD 'analyst_secret_123';
    GRANT CONNECT ON DATABASE analytics_pg TO analyst_read;
    GRANT USAGE ON SCHEMA public TO analyst_read;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analyst_read;
EOSQL
