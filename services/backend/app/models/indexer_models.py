"""Indexer state — the per-chain block cursor (migration 0012).

Postgres is the SOURCE OF TRUTH for the indexer cursor. It previously lived
only in Redis: a flush/restart made the indexer re-initialize at the current
chain head, permanently skipping every block in between — silent payment
loss (no settlement row, no webhook, intent expired while the money sat in
the merchant's wallet). Redis remains a write-through hot cache only.
"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, Integer

from app.models.db_models import Base


class IndexerCursor(Base):
    __tablename__ = "indexer_cursors"

    # One row per chain; chain_id is the natural primary key.
    chain_id = Column(Integer, primary_key=True, autoincrement=False)
    last_block = Column(BigInteger, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
