#!/bin/sh
set -e

echo "Waiting for postgres at ${DB_HOST}:${DB_PORT}..."
while ! nc -z "${DB_HOST}" "${DB_PORT}"; do
  sleep 0.5
done
echo "Postgres is up."

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_superuser

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
