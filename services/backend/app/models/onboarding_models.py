"""Onboarding groundwork models — company profile + consent records.

CompanyProfile is the org's self-declared business identity, one-to-one with
Organization (unique org_id). Every business field is NULLABLE: rows start as
drafts (autosaved from the company-info step) and only the submit endpoint
validates completeness, stamps `submitted_at`, and advances the org's
`onboarding_status`. After submission the profile is read-only through the
API. Allowed enum values are enforced at the Pydantic layer
(onboarding_schemas.py) — columns store plain text, matching the repo's
role/status column convention (SQLite-safe).

ConsentRecord is an append-only audit trail of legal-document acceptances:
one row per (user, document, acceptance). Re-accepting after a version bump
inserts fresh rows; the latest row per document is compared against
app.legal_versions.CURRENT_VERSIONS.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)

from app.models.auth_models import _JSONB, _UUID
from app.models.db_models import Base


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id = Column(
        _UUID(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    org_id = Column(
        _UUID(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Company identity
    legal_name = Column(Text, nullable=True)
    trading_name = Column(Text, nullable=True)
    country = Column(String(2), nullable=True)  # ISO 3166-1 alpha-2
    registration_number = Column(Text, nullable=True)
    tax_or_vat_number = Column(Text, nullable=True)
    website = Column(Text, nullable=True)

    # Operations — enum values validated in onboarding_schemas.py
    business_category = Column(Text, nullable=True)
    expected_monthly_volume = Column(Text, nullable=True)  # EUR bands
    countries_served = Column(_JSONB(), nullable=True)  # list of ISO alpha-2
    primary_stablecoin = Column(Text, nullable=True)

    # Declarations — the first two must be True at submit; has_pep accepts
    # both values but must be answered (not NULL) at submit.
    no_sanctioned_countries = Column(Boolean, nullable=True)
    no_prohibited_activities = Column(Boolean, nullable=True)
    has_pep = Column(Boolean, nullable=True)

    # NULL = draft. Set exactly once by the submit endpoint.
    submitted_at = Column(DateTime(timezone=True), nullable=True)

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


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id = Column(
        _UUID(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type = Column(Text, nullable=False)  # 'tos' | 'privacy'
    document_version = Column(Text, nullable=False)
    accepted_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index(
            "idx_consents_user_doc_accepted",
            "user_id",
            "document_type",
            "accepted_at",
        ),
    )
