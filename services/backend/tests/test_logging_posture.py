"""
RSends Backend — Test: log-level posture (prod INFO, noisy third parties WARNING).

Production logs ran at DEBUG because the level was driven by the DEBUG env var
alone. The level now follows the unified production posture (is_prod_posture —
the same H6 pattern the validate_settings/validate_dev_flags prod guards use):

  prod posture → root INFO; httpx / httpcore / sqlalchemy.engine forced to
                 WARNING (their WARNING+ records still flow — the Redis
                 incident diagnostics stay visible).
  dev posture  → unchanged: root DEBUG, sqlalchemy.engine INFO, httpx/httpcore
                 inherit the root (not forced).

Redaction (see test_logging_redaction.py) is attached in BOTH postures —
independent of level, because the Alchemy key leaked at INFO.

Come eseguire:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_logging_posture.py -v
"""

import io
import logging

import pytest

from app.logging_config import SecretRedactionFilter, setup_logging
from tests._logging_helpers import restore_logging_state


@pytest.fixture(autouse=True)
def _restore_logging():
    with restore_logging_state():
        yield


def test_prod_posture_root_info_and_noisy_loggers_warning():
    setup_logging(debug=False, prod_posture=True)
    assert logging.getLogger().level == logging.INFO
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING
    assert logging.getLogger("uvicorn.access").level == logging.WARNING
    assert logging.getLogger("alembic").level == logging.INFO


def test_httpcore_children_inherit_warning():
    """httpcore.http11 / httpcore.connection have no explicit level — setting
    the parent must silence them below WARNING via inheritance."""
    setup_logging(debug=False, prod_posture=True)
    child = logging.getLogger("httpcore.http11")
    assert child.level == logging.NOTSET  # not forced individually
    assert child.getEffectiveLevel() == logging.WARNING


def test_prod_posture_third_party_warning_still_emitted():
    """Do not silence errors: third-party WARNING/ERROR must still come
    through (the last Redis incident was diagnosed from exactly those)."""
    setup_logging(debug=False, prod_posture=True)
    stream = io.StringIO()
    logging.getLogger().handlers[0].setStream(stream)

    logging.getLogger("httpx").info("HTTP Request: GET https://x.example/")
    logging.getLogger("httpx").warning("connection pool exhausted")
    logging.getLogger("sqlalchemy.engine").error("could not connect")

    out = stream.getvalue()
    assert "HTTP Request" not in out  # INFO suppressed in prod
    assert "connection pool exhausted" in out
    assert "could not connect" in out


def test_dev_posture_unchanged():
    """Development/test behavior stays exactly as before: root DEBUG,
    sqlalchemy.engine INFO, httpx/httpcore inherit the root level."""
    setup_logging(debug=True, prod_posture=False)
    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("sqlalchemy.engine").level == logging.INFO
    assert logging.getLogger("httpx").level == logging.NOTSET
    assert logging.getLogger("httpcore").level == logging.NOTSET
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger("uvicorn.access").level == logging.WARNING


@pytest.mark.parametrize("debug,prod_posture", [(False, True), (True, False)])
def test_redaction_filter_attached_in_both_postures(debug, prod_posture):
    """Redaction is mandatory and independent of level — the Alchemy key
    leaks at INFO, so a level change alone would not fix it."""
    setup_logging(debug=debug, prod_posture=prod_posture)
    handler = logging.getLogger().handlers[0]
    assert any(isinstance(f, SecretRedactionFilter) for f in handler.filters)


def _install_uvicorn_default_handlers():
    """Reproduce uvicorn's default LOGGING_CONFIG: 'uvicorn' and
    'uvicorn.access' own dedicated handlers and do NOT propagate; 'uvicorn.error'
    propagates into 'uvicorn'. Without this, the test env has no uvicorn
    handlers at all and the routing fix is untestable (the exact reason this
    leak shipped)."""
    own = {}
    for name in ("uvicorn", "uvicorn.access"):
        lg = logging.getLogger(name)
        h = logging.StreamHandler(io.StringIO())
        lg.handlers[:] = [h]
        lg.propagate = False
        own[name] = h
    logging.getLogger("uvicorn.error").handlers[:] = []
    logging.getLogger("uvicorn.error").propagate = True
    return own


@pytest.mark.parametrize("debug,prod_posture", [(False, True), (True, False)])
def test_uvicorn_loggers_routed_through_root(debug, prod_posture):
    """Uvicorn's default config gives 'uvicorn'/'uvicorn.access' their own
    NON-propagating handlers, so their records — notably uvicorn.error
    tracebacks — would bypass the root redaction filter for the whole process.
    setup_logging must re-point them at root (clear handlers + propagate) in
    BOTH postures so redaction is universal."""
    _install_uvicorn_default_handlers()
    setup_logging(debug=debug, prod_posture=prod_posture)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        assert lg.handlers == [], f"{name} still has its own handler"
        assert lg.propagate is True, f"{name} does not propagate to root"


def test_uvicorn_error_traceback_reaches_root_redacted():
    """The concrete leak this closes: an unhandled error logged by
    uvicorn.error (with a secret in the exception) — through uvicorn's OWN
    handler by default — must instead reach the root handler AND be masked."""
    _install_uvicorn_default_handlers()
    setup_logging(debug=False, prod_posture=True)
    stream = io.StringIO()
    logging.getLogger().handlers[0].setStream(stream)

    ulog = logging.getLogger("uvicorn.error")
    try:
        raise ConnectionError("connect failed: rediss://:s3cret@red-abc:6379/0")
    except ConnectionError:
        ulog.exception("Exception in ASGI application")

    out = stream.getvalue()
    assert out, "uvicorn.error record never reached the root handler"
    assert "s3cret" not in out
    assert "rediss://:[REDACTED]@red-abc:6379/0" in out
