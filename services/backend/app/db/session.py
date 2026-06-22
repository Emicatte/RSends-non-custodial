"""
RSend Database Session — PostgreSQL only (production).
SQLite supportato SOLO per test unitari.
"""

import asyncio
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.config import get_settings
from app.models.db_models import Base
from app.models import audit_models as _audit_models        # noqa: F401 — registra tabella audit_log (tamper-evident) in Base.metadata
from app.models import settlement_models as _settlement_models  # noqa: F401 — registra tabella payment_settlements (on-chain settlement, non-custodial) in Base.metadata
from app.models import aml_models as _aml_models            # noqa: F401 — registra tabella blacklisted_wallets in Base.metadata
from app.models import api_key_models as _apikey_models      # noqa: F401 — registra tabella api_keys in Base.metadata
from app.models import auth_models as _auth_models            # noqa: F401 — registra tabelle users / user_sessions / auth_audit_log in Base.metadata
from app.models import org_models as _org_models              # noqa: F401 — registra tabelle organizations / memberships / org_invites in Base.metadata (referenziata da users.active_org_id)
from app.models import user_routes_models as _user_routes_models  # noqa: F401 — registra tabella user_routes in Base.metadata

settings = get_settings()

# Determina se siamo su SQLite (test) o PostgreSQL (prod)
_is_sqlite = "sqlite" in settings.database_url

if _is_sqlite:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        connect_args={"check_same_thread": False},  # SQLite only
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        """Enable WAL mode and busy timeout for concurrent write safety."""
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
else:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        # ── Connection Pool (CRITICO per produzione) ──
        pool_size=20,            # connessioni permanenti (invariato)
        max_overflow=30,         # connessioni extra sotto carico (totale max: 50)
        pool_timeout=5,          # fast-fail: meglio un 503 rapido di una attesa di 30s
        pool_recycle=1800,       # ricicla connessioni ogni 30min (evita timeout PostgreSQL)
        pool_pre_ping=True,      # verifica connessione prima di usarla
    )

async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def init_db() -> None:
    """Crea tabelle. In produzione usa Alembic."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Chiudi il pool di connessioni."""
    await engine.dispose()


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """Dependency injection per FastAPI."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


# ── SQLite Write Serialization ────────────────────────────────
# SQLite allows only one writer at a time. Under concurrent load,
# even with WAL + busy_timeout, "database is locked" errors occur
# when many coroutines compete for the write lock.
# This asyncio.Lock serializes writes at the application level,
# eliminating contention entirely. No-op for PostgreSQL.
_sqlite_write_lock = None  # lazy-init (needs event loop)


@asynccontextmanager
async def db_write_lock():
    """Serialize DB writes for SQLite. No-op for PostgreSQL."""
    if not _is_sqlite:
        yield
        return
    global _sqlite_write_lock
    if _sqlite_write_lock is None:
        _sqlite_write_lock = asyncio.Lock()
    async with _sqlite_write_lock:
        yield
