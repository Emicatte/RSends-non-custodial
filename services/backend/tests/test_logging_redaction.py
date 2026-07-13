"""
RSends Backend — Test: secret redaction in the logging pipeline.

Production logs leaked secrets at INFO (Alchemy key in the httpx request-URL
line, full redis_url at startup) — lowering levels alone cannot fix that, so a
handler-level redaction filter masks secrets in EVERY emitted record: the
interpolated message (%-args), extra-dict values, and formatted tracebacks.
The mask keeps context (scheme/user/host stay visible, the secret does not).

These tests run the REAL pipeline (logger → root handler → JSON formatter) as
configured by setup_logging(), not the regexes in isolation, so they pin the
attachment point too.

Come eseguire:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_logging_redaction.py -v
"""

import io
import json
import logging

import pytest

from app.logging_config import setup_logging
from tests._logging_helpers import restore_logging_state

MASK = "[REDACTED]"


@pytest.fixture(autouse=True)
def _restore_logging():
    with restore_logging_state():
        yield


def _capture(*, debug: bool = False, prod_posture: bool = True) -> io.StringIO:
    """Configure the real pipeline and swap the handler stream for a StringIO."""
    setup_logging(debug=debug, prod_posture=prod_posture)
    stream = io.StringIO()
    logging.getLogger().handlers[0].setStream(stream)
    return stream


def _records(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def _log() -> logging.Logger:
    return logging.getLogger("app.tests.redaction")


ALCHEMY_KEY = "supersecretalchemykey123"
ALCHEMY_URL = f"https://base-sepolia.g.alchemy.com/v2/{ALCHEMY_KEY}"


# ── API keys embedded in URL paths (the Alchemy RPC form) ─────────────


def test_redact_alchemy_key_in_message():
    stream = _capture()
    _log().info(f'HTTP Request: POST {ALCHEMY_URL} "HTTP/1.1 200 OK"')
    (rec,) = _records(stream)
    assert ALCHEMY_KEY not in rec["message"]
    assert f"https://base-sepolia.g.alchemy.com/v2/{MASK}" in rec["message"]
    assert '"HTTP/1.1 200 OK"' in rec["message"]  # context preserved


def test_redact_alchemy_key_in_percent_args():
    """The httpx sink passes the URL via %-args, not an f-string."""
    stream = _capture()
    _log().info("HTTP Request: %s %s", "POST", ALCHEMY_URL)
    (rec,) = _records(stream)
    assert ALCHEMY_KEY not in rec["message"]
    assert rec["message"] == f"HTTP Request: POST https://base-sepolia.g.alchemy.com/v2/{MASK}"


def test_redact_alchemy_key_in_extra_dict():
    """main.py logs startup config via extra={} — JSON fields must be masked too."""
    stream = _capture()
    _log().info("boot", extra={"rpc": ALCHEMY_URL})
    (rec,) = _records(stream)
    assert rec["rpc"] == f"https://base-sepolia.g.alchemy.com/v2/{MASK}"


def test_redact_alchemy_key_in_traceback():
    """Connection errors embed URLs in exception messages; the formatted
    traceback must be masked (pins the formatter-level override)."""
    stream = _capture()
    try:
        raise ValueError(f"connect failed: {ALCHEMY_URL}")
    except ValueError:
        _log().exception("boom")
    out = stream.getvalue()
    assert ALCHEMY_KEY not in out
    assert f"alchemy.com/v2/{MASK}" in out


# ── Credentialed connection strings ───────────────────────────────────


def test_redact_redis_url_password_keeps_host():
    stream = _capture()
    _log().info("Redis connected: %s", "redis://:s3cret@red-abc123:6379/0")
    (rec,) = _records(stream)
    assert rec["message"] == f"Redis connected: redis://:{MASK}@red-abc123:6379/0"


def test_redact_rediss_and_user_password():
    stream = _capture()
    _log().info("broker: rediss://celery:pw12345@redis.internal:6379/1")
    (rec,) = _records(stream)
    assert rec["message"] == f"broker: rediss://celery:{MASK}@redis.internal:6379/1"


def test_redact_postgresql_password_keeps_user_and_host():
    stream = _capture()
    _log().info(
        "db: postgresql+asyncpg://rpagos:hunter2@db.internal:5432/rpagos"
    )
    (rec,) = _records(stream)
    assert rec["message"] == (
        f"db: postgresql+asyncpg://rpagos:{MASK}@db.internal:5432/rpagos"
    )


def test_redact_redis_url_in_extra_dict():
    """The exact main.py startup shape: extra={"redis": settings.redis_url}."""
    stream = _capture()
    _log().info(
        "RPagos Backend Core started",
        extra={"redis": "rediss://:passw0rd@red-xyz:6379/0", "sentry": False},
    )
    (rec,) = _records(stream)
    assert rec["redis"] == f"rediss://:{MASK}@red-xyz:6379/0"
    assert rec["sentry"] is False


def test_redact_exception_message_with_redis_password():
    """Mimic cache_service: logger.error("Redis connection failed: %s", exc)."""
    stream = _capture()
    exc = ConnectionError(
        "Error connecting to redis://:topsecret@red-abc123:6379/0: timed out"
    )
    _log().error("Redis connection failed: %s", exc)
    (rec,) = _records(stream)
    assert "topsecret" not in rec["message"]
    assert f"redis://:{MASK}@red-abc123:6379/0" in rec["message"]


# ── Bearer tokens ─────────────────────────────────────────────────────


def test_redact_bearer_token():
    stream = _capture()
    _log().info(
        "upstream call failed, headers: Authorization: Bearer "
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.abc-def_ghi"
    )
    (rec,) = _records(stream)
    assert "eyJhbGciOiJIUzI1NiJ9" not in rec["message"]
    assert f"Bearer {MASK}" in rec["message"]


# ── Repo API-key literals (beyond spec minimum, defense-in-depth) ─────


def test_redact_rsend_api_key_shapes():
    stream = _capture()
    _log().info(
        "keys: rsend_live_%s and rsusr_live_%s",
        "ab12cd34" * 6,  # 48 hex chars, the real generator length
        "Uv-3xY_9kQ2mN8pL4sT7wZ1aB5cD0eF",
    )
    (rec,) = _records(stream)
    assert "ab12cd34" not in rec["message"]
    assert f"rsend_live_{MASK}" in rec["message"]
    assert f"rsusr_live_{MASK}" in rec["message"]


def test_redact_rsend_test_environment_keys():
    """Defense-in-depth must cover BOTH environments for both key namespaces —
    the regex must not be narrower than the key namespace (a future
    rsusr_test_ key would otherwise log unredacted)."""
    stream = _capture()
    _log().info(
        "test keys: rsend_test_%s / rsusr_test_%s",
        "deadbeef" * 6,
        "Ab12Cd34Ef56Gh78Ij90Kl",
    )
    (rec,) = _records(stream)
    assert "deadbeef" not in rec["message"]
    assert "Ab12Cd34" not in rec["message"]
    assert f"rsend_test_{MASK}" in rec["message"]
    assert f"rsusr_test_{MASK}" in rec["message"]


# ── No false positives / untouched paths ──────────────────────────────


def test_ordinary_message_untouched():
    stream = _capture()
    msg = "DB status: connected | Pool: 20/50"
    _log().info(msg)
    (rec,) = _records(stream)
    assert rec["message"] == msg


def test_short_v2_path_segment_not_redacted():
    stream = _capture()
    _log().info("GET https://api.example.com/v2/invoices returned 200")
    (rec,) = _records(stream)
    assert "invoices" in rec["message"]
    assert MASK not in rec["message"]


def test_credentialless_url_untouched():
    stream = _capture()
    _log().info("Redis connected: redis://red-abc123:6379/0")
    (rec,) = _records(stream)
    assert rec["message"] == "Redis connected: redis://red-abc123:6379/0"


def test_non_string_extra_values_untouched():
    stream = _capture()
    _log().info("boot", extra={"sentry": True, "port": 6379})
    (rec,) = _records(stream)
    assert rec["sentry"] is True
    assert rec["port"] == 6379


# ── Robustness: logging must never crash the caller ──────────────────


def test_filter_does_not_raise_on_malformed_percent_args():
    """A mismatched %-args call makes record.getMessage() raise. In a *handler
    filter* that raise is NOT contained by logging.Handler.handleError (which
    only guards emit), so it would propagate into the request handler → 500 on
    a path that previously just logged. The filter must fail safe."""
    stream = _capture()
    # Would raise TypeError inside getMessage(): "%d" with a non-int arg.
    _log().info("processed %d items", "not-an-int")
    # No exception propagated; a line was still emitted.
    out = stream.getvalue()
    assert out
    # The unformatted template survives (no interpolation happened); crucially
    # the call did not blow up.
    (rec,) = _records(stream)
    assert "processed %d items" in rec["message"]
