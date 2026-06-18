"""SQLAlchemy models for email+password auth tokens (migration 0031)."""

from sqlalchemy import Column, String, Text, TIMESTAMP, ForeignKey

from app.models.db_models import Base
from app.models.auth_models import _UUID


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id = Column(_UUID(), primary_key=True)
    user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String(128), nullable=False)
    email_at_issue = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    ip_at_issue = Column(String(45), nullable=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(_UUID(), primary_key=True)
    user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String(128), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    ip_at_issue = Column(String(45), nullable=True)
    ip_at_use = Column(String(45), nullable=True)
