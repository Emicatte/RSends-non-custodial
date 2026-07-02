"""
RPagos Backend — End-user auth models (Google OAuth).

Three tables:
- User: one row per Google identity (keyed by `google_sub`).
- UserSession: DB backup of Redis-authoritative sessions (audit/forensics).
- AuthAuditLog: immutable append-only event stream. On PostgreSQL a
  BEFORE UPDATE/DELETE trigger enforces immutability at the DB layer.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Boolean, BigInteger, Date, DateTime, TIMESTAMP, ForeignKey, Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, INET
from sqlalchemy.types import TypeDecorator, CHAR, JSON

from app.models.db_models import Base


# ─────────────────────────────────────────────────────────────
#  Cross-dialect helpers (PostgreSQL in prod, SQLite in tests)
# ─────────────────────────────────────────────────────────────

class _UUID(TypeDecorator):
    """UUID in Postgres, 36-char string in SQLite (test fallback)."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return str(value)


class _INET(TypeDecorator):
    """INET in Postgres, 45-char string in SQLite."""
    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(INET())
        return dialect.type_descriptor(String(45))


class _JSONB(TypeDecorator):
    """JSONB in Postgres, JSON in SQLite."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


# ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    # One account per email, case-insensitively, BY CONSTRUCTION: every auth
    # entry path normalizes to lowercase and guards collisions (409
    # block-and-guide), and this expression index is the DB backstop against
    # a future bug/race. Mirrored by migration 0007 for existing DBs (fresh
    # DBs — incl. all tests — get it via Base.metadata.create_all).
    __table_args__ = (
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id = Column(_UUID(), primary_key=True)
    google_sub = Column(Text, nullable=True, unique=True, index=True)
    github_sub = Column(Text, nullable=True, unique=True, index=True)
    github_username = Column(Text, nullable=True)
    email = Column(Text, nullable=False, index=True)
    email_verified = Column(Boolean, nullable=False, default=False)
    email_verified_at = Column(TIMESTAMP(timezone=True), nullable=True)
    password_hash = Column(String(128), nullable=True)
    password_set_at = Column(TIMESTAMP(timezone=True), nullable=True)
    display_name = Column(Text, nullable=True)
    avatar_url = Column(Text, nullable=True)
    locale = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    last_login_ip = Column(_INET(), nullable=True)

    status = Column(Text, nullable=False, default="active")

    # account_type: 'individual' | 'merchant'. Required, no default — set
    # explicitly at signup (see email_auth_service.signup). DB CHECK constraint
    # `ck_users_account_type` (migration 0037) enforces the allowed values.
    # TODO(account_type): the post-verification onboarding path diverges here —
    # 'individual' -> KYC, 'merchant' -> KYB. Not branched yet; only persisted.
    account_type = Column(String(20), nullable=False)

    # Signup profile fields (migration 0038). NULLABLE — existing accounts
    # predate these and have NULL; new email/password signups set them
    # (required at the SignupRequest layer, not the DB). display_name is derived
    # from first_name + last_name for new signups; existing display_name kept.
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    date_of_birth = Column(Date, nullable=True)            # age >= 18 enforced at signup
    country_of_residence = Column(String(2), nullable=True)  # ISO 3166-1 alpha-2
    newsletter_opt_in = Column(Boolean, nullable=True)      # optional opt-in

    # NOTE: renamed from `metadata` to avoid clash with SQLAlchemy's
    # `Base.metadata` class attribute. Column stays `metadata_json`.
    metadata_json = Column(_JSONB(), nullable=False, default=dict)

    # GDPR art. 17 right-to-erasure (added by migration 0027). Nullable →
    # normal users have all three NULL; set only when deletion is requested.
    # Partial index `idx_users_pending_deletion` covers
    # `deletion_scheduled_for` for the daily cron scan.
    deletion_requested_at = Column(DateTime(timezone=True), nullable=True)
    deletion_scheduled_for = Column(DateTime(timezone=True), nullable=True)
    deletion_reason = Column(Text, nullable=True)

    # use_alter=True breaks the users<->organizations FK cycle
    # (organizations.owner_user_id -> users.id and this column ->
    # organizations.id): SQLAlchemy emits this FK via a separate ALTER after
    # both tables exist, so create_all/drop_all can topo-sort the tables.
    # Schema-equivalent (same column/target/ondelete); requires an explicit name.
    active_org_id = Column(
        _UUID(),
        ForeignKey("organizations.id", ondelete="SET NULL",
                   use_alter=True, name="fk_users_active_org"),
        nullable=True,
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(_UUID(), primary_key=True)
    user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id = Column(Text, nullable=False, unique=True)
    refresh_token_hash = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_used_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(Text, nullable=True)
    ip_address = Column(_INET(), nullable=True)
    user_agent = Column(Text, nullable=True)
    device_fingerprint = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_sessions_user_id", "user_id"),
        Index("idx_sessions_session_id", "session_id"),
    )


class AuthAuditLog(Base):
    """Immutable append-only log of auth events.

    On Postgres a BEFORE UPDATE/DELETE trigger blocks mutation at the DB
    layer. Never mutate rows from application code — only insert.
    """

    __tablename__ = "auth_audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(Text, nullable=False)
    user_id = Column(_UUID(), nullable=True)
    session_id = Column(Text, nullable=True)
    ip_address = Column(_INET(), nullable=True)
    user_agent = Column(Text, nullable=True)
    google_sub = Column(Text, nullable=True)
    correlation_id = Column(Text, nullable=True)
    details = Column(_JSONB(), nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_audit_user_id", "user_id"),
        Index("idx_audit_event_type", "event_type"),
    )
