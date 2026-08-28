"""The auth audit write itself: does the row land, and is a failure legible?

`auth_audit_log.id` was declared `BigInteger`, which compiles to
`BIGINT PRIMARY KEY` on SQLite. That is not SQLite's ROWID alias, so no key was
generated and every insert raised

    (sqlite3.IntegrityError) NOT NULL constraint failed: auth_audit_log.id

which `record_auth_event` swallowed into a `None` return. Under SQLite — which is
what CI runs — EVERY auth audit write had always failed, silently, for as long as
the table has existed. ~880 tests passed around it because nothing had ever
asserted that a row was actually written.

So the assertions here are deliberately about the row and the alarm, not about
the return value:

  • the row is SELECTed back in a separate session, keyed on a marker the test
    chose — not on the id the call returned, which is the thing that lied;
  • a failed write increments a counter, and still does not raise (the audit
    must not block auth);
  • a raising logger cannot report a committed row as a failed write.

Direct-service style vs the test engine (see tests/test_auth_correlation.py).
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql, sqlite

from app.db.session import async_session, engine
from app.middleware.correlation import correlation_id as correlation_ctx
from app.models.auth_models import AuthAuditLog
from app.models.db_models import Base
from app.services import auth_audit
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
    tok = correlation_ctx.set("")
    yield
    correlation_ctx.reset(tok)


async def _rows_marked(marker: str) -> list[AuthAuditLog]:
    """Every audit row carrying `marker` in session_id, read in its OWN session.

    Keyed on the marker rather than on the id `record_auth_event` returned: the
    return value is exactly what this suite must not trust.
    """
    async with async_session() as db:
        return list(
            (
                await db.execute(
                    select(AuthAuditLog).where(AuthAuditLog.session_id == marker)
                )
            ).scalars()
        )


# ── The row lands ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_row_is_actually_written_and_readable():
    """Reading the row back IS the assertion. A non-None return is not.

    This is the case that had always failed under SQLite while the suite stayed
    green: nothing ever went looking for the row.
    """
    marker, cid = f"marker-{uuid4()}", str(uuid4())

    await record_auth_event(
        event_type="login_success",
        session_id=marker,
        correlation_id=cid,
    )

    rows = await _rows_marked(marker)
    assert len(rows) == 1, "the audit row was not written"
    assert rows[0].correlation_id == cid
    assert rows[0].event_type == "login_success"


# ── A failed write is legible, and still does not raise ──────

@pytest.mark.asyncio
async def test_failed_write_increments_the_counter_and_returns_none(monkeypatch):
    """A permanent write failure must be countable, not just a log line nobody
    reads — that silence is what let this bug live. And it must still not raise:
    the audit must never block auth."""
    # Unique label: prometheus counters are process-global, so assert the delta.
    event_type = f"probe_{uuid4().hex[:8]}"
    counter = auth_audit.AUTH_AUDIT_WRITE_FAILURES.labels(event_type=event_type)
    before = counter._value.get()

    class _ExplodingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def add(self, _entry):
            pass

        async def commit(self):
            raise IntegrityError("INSERT INTO auth_audit_log", {}, Exception("boom"))

    monkeypatch.setattr(auth_audit, "async_session", lambda: _ExplodingSession())

    result = await record_auth_event(event_type=event_type)  # must not raise

    assert result is None
    assert counter._value.get() - before == 1


# ── A raising logger cannot fake a failed write ──────────────

@pytest.mark.asyncio
async def test_a_raising_logger_does_not_turn_a_written_row_into_none(monkeypatch):
    """The success log used to sit inside the try that guards the write, so a
    raising formatter or filter returned None after a SUCCESSFUL commit —
    indistinguishable from the row never landing."""
    marker = f"marker-{uuid4()}"

    def _boom(*args, **kwargs):
        raise RuntimeError("logging handler exploded")

    monkeypatch.setattr(auth_audit.logger, "info", _boom)

    result = await record_auth_event(event_type="logout", session_id=marker)

    assert result is not None, "a logging failure was reported as a failed write"
    rows = await _rows_marked(marker)
    assert len(rows) == 1
    assert rows[0].id == result


# ── The DDL that caused all of it ────────────────────────────

def test_the_id_column_generates_a_key_on_both_dialects():
    """SQLite generates a key only for a column declared exactly INTEGER; the
    Postgres column must stay BIGSERIAL (narrowing an append-only audit table to
    int4 would be a real migration, and a ~2.1B row ceiling)."""
    ddl = {
        d.name: str(CreateTable(AuthAuditLog.__table__).compile(dialect=d))
        for d in (sqlite.dialect(), postgresql.dialect())
    }

    assert "id INTEGER NOT NULL" in ddl["sqlite"]
    assert "id BIGSERIAL NOT NULL" in ddl["postgresql"]
