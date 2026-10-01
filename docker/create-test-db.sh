#!/bin/sh
# Runs once, when the Postgres volume is first created.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "CREATE DATABASE eve_test;"
