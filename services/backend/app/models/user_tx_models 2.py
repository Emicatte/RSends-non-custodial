"""User-owned transaction history submitted via RSends.

One row per (user_id, chain_id, tx_hash); scoped by user_id. FK cascades on
user delete. Reuses _UUID / _JSONB TypeDecorators from auth_models (Postgres
native types in prod, SQLite fallback in tests).

`extra_metadata` avoids SQLAlchemy's reserved `metadata` attribute on
Declarative Base.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)

from app.models.db_models import Base
from app.models.auth_models import _UUID, _JSONB


class UserTransaction(Base):
    __tablename__ = "user_transactions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "chain_id", "tx_hash", name="uq_user_tx_hash"
        ),
    )

    id = Column(_UUID(), primary_key=True)
    user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    chain_id = Column(Integer, nullable=False)
    tx_hash = Column(Text, nullable=False)
    wallet_address = Column(Text, nullable=False)

    tx_type = Column(Text, nullable=False)
    tx_status = Column(Text, nullable=False, default="pending")
    direction = Column(Text, nullable=False, default="out")

    token_symbol = Column(Text, nullable=True)
    token_address = Column(Text, nullable=True)
    amount_raw = Column(Text, nullable=True)
    amount_decimal = Column(Numeric(38, 18), nullable=True)
    counterparty_address = Column(Text, nullable=True)

    extra_metadata = Column(_JSONB(), nullable=False, default=dict)
    gas_used = Column(BigInteger, nullable=True)
    gas_price_gwei = Column(Numeric(38, 9), nullable=True)
    block_number = Column(BigInteger, nullable=True)

    submitted_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
