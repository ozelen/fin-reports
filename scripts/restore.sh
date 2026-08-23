#!/bin/sh
# Restore a pg_dump -Fc file. Replaces the current database.
# Uses libpq env: PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE (same as backup.sh).
#
# Local:  docker compose stop api bot
#         docker compose run --rm --entrypoint /bin/sh backup /restore.sh /backups/income-share-YYYYMMDDThhmmssZ.dump
#         docker compose start api bot
# Prod:   same with -f docker-compose.prod.yml
set -eu

PGHOST="${PGHOST:-${POSTGRES_HOST:-db}}"
PGPORT="${PGPORT:-${POSTGRES_PORT:-5432}}"
PGUSER="${PGUSER:-${POSTGRES_USER}}"
PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD}}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB}}"
export PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE

DUMP="${1:-}"
if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
  echo "usage: restore.sh <dump-file>" >&2
  exit 1
fi

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) restoring $DUMP into $PGDATABASE at $PGHOST"
pg_restore --clean --if-exists --no-owner --dbname="$PGDATABASE" "$DUMP"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) done"
