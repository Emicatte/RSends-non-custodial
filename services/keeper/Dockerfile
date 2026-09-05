# ═══════════════════════════════════════════════════════════
#  RSends Auto Split keeper
#
#  Python 3.12 deliberately: CI runs 3.12 and services/backend/.python-version
#  pins 3.12. (services/backend/Dockerfile still says 3.11 — a pre-existing
#  inconsistency, not one to copy into a new service.)
#
#  This image holds a private key at runtime. It gets no build-time secrets, no
#  database client, and no backend source: the keeper reaches the backend over
#  HTTP with a shared secret and never imports `app.*`.
# ═══════════════════════════════════════════════════════════

FROM python:3.12-slim AS base

RUN groupadd -r keeper && useradd -r -g keeper -d /app keeper

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY keeper ./keeper

RUN chown -R keeper:keeper /app
USER keeper

# No entrypoint script: there are no migrations to run and nothing to bootstrap.
# The loop reads its whole configuration from the environment and fails closed
# on anything missing.
CMD ["python", "-m", "keeper"]
