"""
Alembic env.py — async engine support per RSends Backend.

Pattern:
  - async_engine_from_config + pool.NullPool (obbligatorio per DDL migrations)
  - asyncio.run() per event loop isolato
  - Importa tutti i modelli per autogenerate completo
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Importa TUTTI i modelli in modo che Base.metadata li conosca ──────────
# db_models deve essere importato per primo perché definisce Base.
# NON-CUSTODIAL set: no ledger/forwarding/command/strategy/split (sweep custody).
from app.models.db_models import Base  # noqa: F401 — definisce Base
from app.models import audit_models as _audit       # noqa: F401 — tamper-evident audit_log
from app.models import settlement_models as _settle # noqa: F401 — on-chain PaymentMade settlements
from app.models import aml_models as _aml           # noqa: F401 — AML/OFAC tables
from app.models import api_key_models as _apikey    # noqa: F401 — api keys
from app.models import auth_models as _auth         # noqa: F401 — end-user auth tables
from app.models import email_auth_models as _emauth # noqa: F401 — email auth tables
from app.models import invoice_models as _inv       # noqa: F401 — commission invoices
from app.models import merchant_models as _merch    # noqa: F401 — merchant B2B tables
from app.models import merchant_profile_models as _mprof  # noqa: F401 — merchant billing profile
from app.models import notification_models as _notif # noqa: F401 — notifications
from app.models import org_models as _org           # noqa: F401 — organizations / memberships
from app.models import user_api_keys_models as _uak # noqa: F401 — user-managed api keys
from app.models import user_contacts_models as _uc  # noqa: F401 — user contacts
from app.models import user_routes_models as _ur    # noqa: F401 — user-owned saved routes
from app.models import user_tx_models as _utx       # noqa: F401 — user tx history
from app.models import user_wallets_models as _uw   # noqa: F401 — user linked wallets

from app.config import get_settings

# ── Config Alembic ────────────────────────────────────────────────────────
config = context.config

# Sovrascrivi l'URL placeholder con quello reale da app.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Configura logging da alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata per autogenerate: include tutte le tabelle registrate in Base
target_metadata = Base.metadata


# ── Modalità OFFLINE — emette SQL senza connessione live ──────────────────

def run_migrations_offline() -> None:
    """Genera SQL su stdout; non richiede connessione DB attiva."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Modalità ONLINE — esegue migrazione su DB live ────────────────────────

def do_run_migrations(connection: Connection) -> None:
    """Configura il contesto e lancia le migrazioni su connessione sincrona."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Crea async engine ed esegue migrazioni tramite run_sync.

    NullPool è obbligatorio per contesti di migrazione: evita connessioni
    bloccate durante operazioni DDL che non devono essere condivise nel pool.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point per modalità online: esegue la coroutine async in modo sincrono.

    asyncio.run() crea sempre un event loop fresco, evitando conflitti
    con loop pre-esistenti (es. ambienti di test, Jupyter).
    """
    asyncio.run(run_async_migrations())


# ── Dispatch offline / online ─────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
