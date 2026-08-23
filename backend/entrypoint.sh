#!/bin/sh
set -e

# TrueNAS may inject DB_*= empty/whitespace; ${VAR:-} does not treat that as unset.
_host=$(printf '%s' "${DB_HOST}" | tr -d '[:space:]')
[ -n "$_host" ] || _host=$(printf '%s' "${POSTGRES_HOST}" | tr -d '[:space:]')
[ -n "$_host" ] || _host=db

_port=$(printf '%s' "${DB_PORT}" | tr -d '[:space:]')
case "$_port" in ''|*[!0-9]*) _port=$(printf '%s' "${POSTGRES_PORT}" | tr -d '[:space:]') ;; esac
case "$_port" in ''|*[!0-9]*) _port=5432 ;; esac
case "$_port" in
  ''|*[!0-9]*)
    echo "Invalid postgres port after fallbacks (DB_PORT='${DB_PORT}' POSTGRES_PORT='${POSTGRES_PORT}'). Set POSTGRES_PORT to a number." >&2
    exit 1
    ;;
esac

DB_HOST="$_host"
DB_PORT="$_port"
export DB_HOST DB_PORT

echo "Waiting for postgres at ${DB_HOST}:${DB_PORT} (nc -z ${DB_HOST} ${DB_PORT})"
while ! nc -z "${DB_HOST}" "${DB_PORT}"; do
  sleep 0.5
done
echo "Postgres is up."

python manage.py migrate --noinput

# Bot (and other one-off commands) reuse this image: skip gunicorn.
if [ "$#" -gt 0 ]; then
  exec "$@"
fi

mkdir -p /app/staticfiles /app/media
chmod 777 /app/staticfiles /app/media 2>/dev/null || true
python manage.py collectstatic --noinput
python manage.py seed_superuser

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
