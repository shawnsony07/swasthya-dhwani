#!/bin/sh
# Entrypoint for the api container: run migrations, then start uvicorn.
# Kept as a plain shell wrapper (not a separate compose step) per
# docs/architecture.md section 2 / the task brief.
set -e

echo "[entrypoint] Running alembic upgrade head..."
alembic upgrade head

echo "[entrypoint] Starting uvicorn..."
exec uvicorn swasthya.api.app:app --host 0.0.0.0 --port 8000
