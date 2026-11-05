#!/bin/sh
# Runs once, on first start of the postgres container: one server, three databases.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE DATABASE mlflow;
CREATE DATABASE airflow;
SQL
