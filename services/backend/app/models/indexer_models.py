"""Indexer state — the per-chain block cursor (migration 0012).

Postgres is the SOURCE OF TRUTH for the indexer cursor. It previously lived
only in Redis: a flush/restart made the indexer re-initialize at the current
chain head, permanently skipping every block in between — silent payment
loss (no settlement row, no webhook, intent expired while the money sat in
the merchant's wallet). Redis remains a write-through hot cache only.
"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime

from app.models.db_models import Base


class IndexerCursor(Base):
    __tablename__ = "indexer_cursors"

    # One row per chain; chain_id is the natural primary key.
    #
    # BigInteger, not Integer (widened in migration 0020): chain ids are not all
    # small. TRON's are the low 4 bytes of the network's genesis hash read as
    # UNSIGNED, and Nile's — 3448148188 — is above the 2147483647 ceiling of a
    # Postgres INTEGER. SQLite would have stored it regardless, so this is a
    # column the test suite cannot defend on its own; see
    # test_migrations_postgres.py::test_a_tron_testnet_chain_id_fits_after_0020.
    chain_id = Column(BigInteger, primary_key=True, autoincrement=False)
    last_block = Column(BigInteger, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
