# syntax=docker/dockerfile:1
# Multi-stage build for the FastAPI triage API (src/swasthya/api/app.py).
# Build context MUST be the repo root, e.g.:
#   docker build -f docker/api.Dockerfile .
# (docker-compose.yml sets context: .. / dockerfile: docker/api.Dockerfile)

FROM python:3.11-slim AS builder

WORKDIR /build

# System deps needed to build wheels for psycopg[binary] etc. are avoided by
# using the binary wheel extra, but keep build-essential in case any
# transitive dependency needs to compile.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

# Install into a venv so it can be copied cleanly into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

FROM python:3.11-slim AS runtime

# Non-root user.
RUN groupadd --system swasthya && useradd --system --gid swasthya --create-home swasthya

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/src ./src
COPY --from=builder /build/migrations ./migrations
COPY --from=builder /build/alembic.ini ./alembic.ini
COPY docker/api-entrypoint.sh /app/entrypoint.sh

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN chmod +x /app/entrypoint.sh && chown -R swasthya:swasthya /app

USER swasthya

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
