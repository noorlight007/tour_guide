#!/bin/sh
set -e

echo "==> Starting Celery Beat…"
exec celery -A tour_management beat \
    --loglevel="${CELERY_LOG_LEVEL:-info}" \
    --scheduler django_celery_beat.schedulers:DatabaseScheduler
    # ↑ Replace "config" with your Django project name.
    # Using DatabaseScheduler so schedules are stored in Postgres (recommended).
    # If you prefer the file-based scheduler, replace the --scheduler line with:
    #   --schedule /app/celerybeat/celerybeat-schedule