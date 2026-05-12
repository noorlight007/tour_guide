# ─────────────────────────────────────────────
#  Stage 1 – dependency builder
# ─────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build-time system deps (for psycopg2, Pillow, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a prefix so we can copy them cleanly
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ─────────────────────────────────────────────
#  Stage 2 – runtime image
# ─────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Runtime system deps only (libpq for psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy project source
COPY . .

# Collect static files (reads SECRET_KEY from env at build time if needed)
# Pass a dummy key so collectstatic doesn't fail; real key comes from .env at runtime
RUN SECRET_KEY=dummy-secret-for-build \
    python manage.py collectstatic --noinput

# Create a non-root user for security
RUN addgroup --system django && adduser --system --ingroup django django
USER django

EXPOSE 8000

# entrypoint handles migrations then hands off to gunicorn
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]