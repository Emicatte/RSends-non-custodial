#!/bin/sh
set -e

# Run migrations at boot ONLY when not handled by a pre-deploy step.
# Default (var unset) = "1" = preserve historical behavior (migrate on boot).
# Set RUN_MIGRATIONS_ON_BOOT=0 in the Render dashboard once the
# Pre-Deploy Command (`alembic upgrade head`) is configured, so the web
# container no longer races other replicas / restarts on schema changes.
if [ "${RUN_MIGRATIONS_ON_BOOT:-1}" = "1" ]; then
  echo "[entrypoint] running alembic upgrade head"
  alembic upgrade head
else
  echo "[entrypoint] skipping alembic upgrade head (RUN_MIGRATIONS_ON_BOOT=${RUN_MIGRATIONS_ON_BOOT}) — handled by pre-deploy"
fi

echo "[entrypoint] starting uvicorn on port ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 --timeout-graceful-shutdown 30
