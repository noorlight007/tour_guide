#!/bin/sh
set -e

echo "==> Starting Celery Worker…"
exec celery -A config worker \
    --loglevel="${CELERY_LOG_LEVEL:-info}" \
    --concurrency="${CELERY_CONCURRENCY:-4}" \
    --max-tasks-per-child="${CELERY_MAX_TASKS_PER_CHILD:-100}"
    # ↑ Replace "config" with your Django project name (same as wsgi module root)