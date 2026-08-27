"""Correlation id reaches the auth audit row.

PR #79 gave every login failure a UUID, sent it upstream as
X-Request-ID/X-Correlation-ID and showed it to the user to quote. The join it
promised did not exist: the web proxy dropped the headers, CorrelationMiddleware
never published the id where route handlers look for it, and
`record_auth_event` required callers to pass it explicitly — which the
email-auth service does at none of its five call sites. Every login, signup and
verification event was written with an empty `correlation_id`.

Pinned here, backend half:
  • CorrelationMiddleware publishes the id on `request.state` (what
    auth_routes._correlation_id reads) as well as in the contextvar, and reuses
    an inbound header instead of generating a fresh id;
  • `record_auth_event` falls back to that contextvar, so a caller that passes
    nothing still writes a joinable row, and an explicit argument still wins.

Direct-service style vs the test engine (see tests/test_auth_email_collision.py).
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import async_session, engine
from app.middleware.correlation import (
    CorrelationMiddleware,
    correlation_id as correlation_ctx,
    set_correlation_id,
)
from app.models.auth_models import AuthAuditLog
from app.models.db_models import Base
from app.services.auth_audit import record_auth_event


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def clear_correlation_ctx():
    """Never let one test's id leak into the next — the whole point is that
    the value is picked up implicitly."""
    tok = correlation_ctx.set("")
    yield
    correlation_ctx.reset(tok)


async def _row(entry_id: int | None) -> AuthAuditLog:
    """Fetch the row `record_auth_event` just wrote, by the id it returned.

    Keyed on the id rather than "the only row in the table": the audit log is
    append-only and the suite's drop_all teardown is not reliable locally
    (`organizations` has dependent objects), so rows from earlier tests can
    still be present. A returned id of None means the write itself failed.
    """
    assert entry_id is not None, "record_auth_event returned None — write failed"
    async with async_session() as db:
        row = (
            await db.execute(
                select(AuthAuditLog).where(AuthAuditLog.id == entry_id)
            )
        ).scalar_one()
    return row


# ── record_auth_event picks up the ambient correlation id ────

@pytest.mark.asyncio
async def test_audit_row_inherits_the_request_correlation_id():
    """The failing case before this change: a caller that passes no
    correlation_id — i.e. every email-auth call site — wrote an unjoinable row."""
    cid = str(uuid4())
    set_correlation_id(cid)

    entry_id = await record_auth_event(
        event_type="email_login", user_id=str(uuid4())
    )

    assert (await _row(entry_id)).correlation_id == cid


@pytest.mark.asyncio
async def test_explicit_correlation_id_wins_over_the_context():
    cid_ctx, cid_arg = str(uuid4()), str(uuid4())
    set_correlation_id(cid_ctx)

    entry_id = await record_auth_event(
        event_type="refresh_reuse_detected", correlation_id=cid_arg
    )

    assert (await _row(entry_id)).correlation_id == cid_arg


@pytest.mark.asyncio
async def test_no_correlation_id_anywhere_stays_null():
    """Outside a request (Celery bootstrap, scripts) the column stays NULL
    rather than an empty string, so `WHERE correlation_id IS NULL` means what
    it says."""
    entry_id = await record_auth_event(event_type="logout")

    assert (await _row(entry_id)).correlation_id is None


# ── CorrelationMiddleware publishes the id where routes read it ──

def _app_echoing_request_state() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)

    @app.get("/probe")
    async def probe(request: Request):
        # Exactly what auth_routes._correlation_id does.
        return {"state_cid": getattr(request.state, "correlation_id", None)}

    return app


def test_middleware_publishes_the_id_on_request_state():
    cid = str(uuid4())
    with TestClient(_app_echoing_request_state()) as client:
        res = client.get("/probe", headers={"X-Correlation-ID": cid})

    assert res.json()["state_cid"] == cid
    # And still echoed back, as before.
    assert res.headers["X-Correlation-ID"] == cid


def test_middleware_generates_an_id_when_the_client_sends_none():
    with TestClient(_app_echoing_request_state()) as client:
        res = client.get("/probe")

    generated = res.json()["state_cid"]
    assert generated
    assert res.headers["X-Correlation-ID"] == generated
