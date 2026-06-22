"""
RSends Backend — Shared SQLAlchemy TypeDecorators (cross-dialect).

Extracted from the (now removed) custodial ledger_models module so that
the surviving models (invoices, merchant profile, command-center config,
audit log) keep working without pulling in any custodial double-entry
ledger code.

  - JSONBType      : JSONB on PostgreSQL, JSON elsewhere (SQLite tests)
  - InetType       : INET on PostgreSQL, VARCHAR(45) elsewhere
  - BigIntegerType : BIGINT on PostgreSQL, INTEGER on SQLite (autoincrement)
"""

from sqlalchemy import BigInteger, Integer, String, TypeDecorator, JSON
from sqlalchemy.dialects.postgresql import INET, JSONB


class JSONBType(TypeDecorator):
    """JSONB su PostgreSQL, JSON su SQLite/altri dialect."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class InetType(TypeDecorator):
    """INET su PostgreSQL, VARCHAR(45) su SQLite/altri dialect."""
    impl = String(45)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(INET())
        return dialect.type_descriptor(String(45))


class BigIntegerType(TypeDecorator):
    """BIGINT su PostgreSQL, INTEGER su SQLite (per autoincrement)."""
    impl = BigInteger
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(Integer())
        return dialect.type_descriptor(BigInteger())
