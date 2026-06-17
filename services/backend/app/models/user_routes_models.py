"""User-owned saved routing configurations.

One row per persisted route; scoped by user_id. FK cascades on user delete.
Reuses _UUID / _JSONB TypeDecorators from auth_models (Postgres-native types
in prod, SQLite fallback in tests).
"""

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, Text, func,
)

from app.models.db_models import Base
from app.models.auth_models import _UUID, _JSONB


class UserRoute(Base):
    __tablename__ = "user_routes"

    id = Column(_UUID(), primary_key=True)
    user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(Text, nullable=False)
    route_config = Column(_JSONB(), nullable=False)
    is_favorite = Column(Boolean, nullable=False, default=False)
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
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    use_count = Column(Integer, nullable=False, default=0)
