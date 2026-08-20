#!/bin/sh
# Postgres dump. Runs inside the backup container (postgres:16-alpine).
#
# One-shot:  docker compose run --rm --entrypoint /bin/sh backup /backup.sh
# Scheduled: docker compose up -d backup
set -eu

DEST="${BACKUP_DIR:-/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

dump() {
  mkdir -p "$DEST"
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  tmp="$DEST/income-share-$stamp.dump.tmp"
  out="$DEST/income-share-$stamp.dump"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) dumping $PGDATABASE to $out"
  pg_dump -Fc -f "$tmp"
  mv "$tmp" "$out"
  find "$DEST" -name 'income-share-*.dump' -type f -mtime +"$KEEP_DAYS" -delete
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) done (keeping ${KEEP_DAYS}d)"
}

dump
if [ "${1:-}" = "--loop" ]; then
  echo "next dump in ${INTERVAL}s"
  while true; do
    sleep "$INTERVAL"
    dump
  done
fi
