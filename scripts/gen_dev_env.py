#!/usr/bin/env python3
"""Generate local DEVELOPMENT env files for a one-command bootstrap.

Writes two gitignored files with matched shared secrets:
  - services/backend/.env   (FastAPI, development mode)
  - apps/web/.env.local      (Next.js)

Design notes
------------
- Dev convenience comes from *development mode* (DEBUG=true, ENVIRONMENT=development),
  which makes app/config.py's `is_prod` False and skips every production-only guard.
  The production validation in config.py is NOT weakened — we only supply a local .env.
- The always-on `ALCHEMY_API_KEY` non-empty check is satisfied with a placeholder
  (RPC calls aren't exercised by a plain boot / UI viewing).
- INTERNAL_PROXY_SECRET and HMAC_SECRET must be identical on both sides; this script
  is the single source that keeps them matched.
- Idempotent: an existing file is never overwritten (so secrets are stable across runs).
  If backend/.env already exists, its secrets are reused when creating web/.env.local.

These are DEV-ONLY secrets. The files are gitignored — never commit them.
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path

# Repo root = parent of this script's directory (scripts/).
ROOT = Path(__file__).resolve().parent.parent
BACKEND_ENV = ROOT / "services" / "backend" / ".env"
WEB_ENV = ROOT / "apps" / "web" / ".env.local"


def _gen() -> str:
    """32 random bytes hex-encoded -> 64 chars (>=32 for HMAC, >=64 for JWT)."""
    return secrets.token_hex(32)


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def _backend_template(hmac: str, jwt: str, proxy: str, admin: str) -> str:
    return f"""\
# ─────────────────────────────────────────────────────────────
# Auto-generated local DEVELOPMENT env — DO NOT COMMIT.
# Regenerate by deleting this file and running `make setup`.
# Production validation in app/config.py is untouched: dev mode
# (DEBUG=true + ENVIRONMENT=development) skips the prod-only guards.
# ─────────────────────────────────────────────────────────────
ENVIRONMENT=development
DEBUG=true

# Local infra (docker-compose.dev.yml: db=postgres:16, redis:7)
DATABASE_URL=postgresql+asyncpg://rsend:rsend_dev_password@localhost:5432/rsend_dev
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# App URLs
APP_URL=http://localhost:3000
FRONTEND_URL=http://localhost:3000
EMAIL_DEV_MODE=true

# Anti-replay: keep legacy wallet sigs OFF even in dev (prod-forbidden anyway)
WALLET_AUTH_ALLOW_LEGACY=false

# Placeholder so the always-on ALCHEMY_API_KEY check passes (no real RPC in dev)
ALCHEMY_API_KEY=dev-placeholder-not-a-real-key

# Dev secrets (generated). HMAC + INTERNAL_PROXY are mirrored on the Next.js side.
# ADMIN_API_TOKEN is backend-only (X-Admin-Token bearer) and deliberately
# distinct from HMAC_SECRET.
HMAC_SECRET={hmac}
AUTH_JWT_SECRET={jwt}
INTERNAL_PROXY_SECRET={proxy}
ADMIN_API_TOKEN={admin}

# Optional integrations stay empty in dev
TELEGRAM_BOT_TOKEN=
"""


def _web_template(hmac: str, proxy: str, nextauth: str) -> str:
    return f"""\
# ─────────────────────────────────────────────────────────────
# Auto-generated local DEVELOPMENT env — DO NOT COMMIT.
# INTERNAL_PROXY_SECRET and HMAC_SECRET MUST match services/backend/.env.
# ─────────────────────────────────────────────────────────────
RPAGOS_BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_RPAGOS_BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_API_URL=http://localhost:8000

# Shared secrets — must equal the backend values
INTERNAL_PROXY_SECRET={proxy}
HMAC_SECRET={hmac}

# NextAuth (dev)
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET={nextauth}

NEXT_PUBLIC_TARGET_CHAIN_ID=8453
"""


def main() -> None:
    created: list[str] = []
    skipped: list[str] = []

    # ── Backend .env: source of truth for the shared secrets ──
    if BACKEND_ENV.exists():
        existing = _parse_env(BACKEND_ENV)
        hmac = existing.get("HMAC_SECRET") or _gen()
        proxy = existing.get("INTERNAL_PROXY_SECRET") or _gen()
        skipped.append(str(BACKEND_ENV.relative_to(ROOT)))
    else:
        hmac, proxy = _gen(), _gen()
        BACKEND_ENV.write_text(_backend_template(hmac, _gen(), proxy, _gen()))
        created.append(str(BACKEND_ENV.relative_to(ROOT)))

    # ── Web .env.local: reuse the backend's shared secrets ──
    if WEB_ENV.exists():
        skipped.append(str(WEB_ENV.relative_to(ROOT)))
    else:
        WEB_ENV.write_text(_web_template(hmac, proxy, _gen()))
        created.append(str(WEB_ENV.relative_to(ROOT)))

    for p in created:
        print(f"  generated  {p}")
    for p in skipped:
        print(f"  kept       {p} (already exists)")
    if created:
        print("  → dev-only secrets; these files are gitignored. Never commit them.")


if __name__ == "__main__":
    main()
