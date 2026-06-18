"""User-owned address book (contacts) synced to the backend on auth.

One row per (user_id, address); scoped by user_id. FK cascades on user delete.
Reuses _UUID / _JSONB TypeDecorators from auth_models (Postgres native types in
prod, SQLite fallback in tests).

`extra_metadata` avoids SQLAlchemy's reserved `metadata` attribute on
Declarative Base.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)

from app.models.db_models import Base
from app.models.auth_models import _UUID, _JSONB


class UserContact(Base):
    __tablename__ = "user_contacts"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "address", name="uq_user_contact_address"
        ),
    )

    id = Column(_UUID(), primary_key=True)
    user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    address = Column(Text, nullable=False)
    label = Column(Text, nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    tx_count = Column(Integer, nullable=False, default=0)

    extra_metadata = Column(_JSONB(), nullable=False, default=dict)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
