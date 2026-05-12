#!/bin/sh
set -e

echo "==> Running database migrations…"
python manage.py migrate --noinput

echo "==> Starting Gunicorn…"
exec gunicorn \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    config.wsgi:application
    # ↑ Replace "config.wsgi" with your actual wsgi module (e.g. myproject.wsgi)