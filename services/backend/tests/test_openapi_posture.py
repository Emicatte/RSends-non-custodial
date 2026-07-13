"""Prod posture must expose NO schema surface: /docs, /redoc AND /openapi.json.

/docs was already debug-gated and redoc_url is permanently None, but FastAPI's
default openapi_url stayed on — the full API schema was public in production.
The app is built at import time from get_settings().debug, so posture is
exercised via a subprocess import (same pattern as the console-script alembic
tests: no reload() side effects in-process).
"""

import os
import subprocess
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]

_PROBE = (
    "from app.main import app;"
    "print(app.docs_url, app.redoc_url, app.openapi_url, sep='|')"
)


def _import_app(debug: str) -> str:
    env = {
        **os.environ,
        "DATABASE_URL": "sqlite+aiosqlite://",
        "DEBUG": debug,
        "ENVIRONMENT": "test",
        "REDIS_URL": "redis://localhost:6379/0",
    }
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=_BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


def test_prod_posture_hides_docs_redoc_and_openapi():
    assert _import_app(debug="false") == "None|None|None"


def test_debug_posture_keeps_docs_and_openapi():
    assert _import_app(debug="true") == "/docs|None|/openapi.json"
