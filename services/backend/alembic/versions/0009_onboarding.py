"""staged onboarding: org status fields, company profiles, consents, age attestation

Staged merchant onboarding groundwork. Four pieces:

1. organizations.onboarding_status / activation_status — the two independent
   state fields. onboarding_status is added with server_default
   'company_submitted' so every PRE-EXISTING org is backfilled to full testnet
   access (grandfathering: nobody is locked out by the new gates), then the
   default is flipped to 'created' so future non-ORM inserts fail closed.
   activation_status defaults to 'not_started' for everyone — no org is
   business-verified yet; nothing in-app transitions it (future provider slot).

2. users.age_attested / age_attested_at — 18+ attestation flag + timestamp.
   Backfilled false/NULL: existing users attest at the consent interstitial on
   next login (they also have no consent_records, so the guard routes them
   there anyway).

3. company_profiles — one-to-one org business profile (draft-then-submit).

4. consent_records — append-only legal-document acceptance trail.

Idempotent: the non-custodial baseline builds the schema from the live ORM via
Base.metadata.create_all, so a DB created after these models were added already
has everything; each piece is applied only if missing.

Revision ID: 0009_onboarding
Revises: 0008_org_settlement_wallet
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0009_onboarding"
down_revision = "0008_org_settlement_wallet"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return any(col["name"] == column for col in _inspector().get_columns(table))


def _has_table(table: str) -> bool:
    return _inspector().has_table(table)


def _uuid_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import UUID as PG_UUID

        return PG_UUID(as_uuid=True)
    return sa.CHAR(36)


def _jsonb_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        return JSONB()
    return sa.JSON()


def upgrade() -> None:
    # ── 1. Organization status fields ────────────────────────────
    if not _has_column("organizations", "onboarding_status"):
        # server_default 'company_submitted' IS the backfill for existing rows…
        op.add_column(
            "organizations",
            sa.Column(
                "onboarding_status",
                sa.Text(),
                nullable=False,
                server_default="company_submitted",
            ),
        )
        # …then flip the default so future non-ORM inserts start fail-closed.
        # batch_alter_table: plain ALTER on Postgres, table-recreate on SQLite
        # (which has no ALTER COLUMN SET DEFAULT).
        with op.batch_alter_table("organizations") as batch:
            batch.alter_column(
                "onboarding_status",
                server_default="created",
                existing_type=sa.Text(),
                existing_nullable=False,
            )
    if not _has_column("organizations", "activation_status"):
        op.add_column(
            "organizations",
            sa.Column(
                "activation_status",
                sa.Text(),
                nullable=False,
                server_default="not_started",
            ),
        )

    # ── 2. User age attestation ──────────────────────────────────
    if not _has_column("users", "age_attested"):
        op.add_column(
            "users",
            sa.Column(
                "age_attested",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if not _has_column("users", "age_attested_at"):
        op.add_column(
            "users",
            sa.Column("age_attested_at", sa.TIMESTAMP(timezone=True), nullable=True),
        )

    # ── 3. company_profiles ──────────────────────────────────────
    if not _has_table("company_profiles"):
        op.create_table(
            "company_profiles",
            sa.Column("id", _uuid_type(), primary_key=True),
            sa.Column(
                "org_id",
                _uuid_type(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
                index=True,
            ),
            sa.Column("legal_name", sa.Text(), nullable=True),
            sa.Column("trading_name", sa.Text(), nullable=True),
            sa.Column("country", sa.String(2), nullable=True),
            sa.Column("registration_number", sa.Text(), nullable=True),
            sa.Column("tax_or_vat_number", sa.Text(), nullable=True),
            sa.Column("website", sa.Text(), nullable=True),
            sa.Column("business_category", sa.Text(), nullable=True),
            sa.Column("expected_monthly_volume", sa.Text(), nullable=True),
            sa.Column("countries_served", _jsonb_type(), nullable=True),
            sa.Column("primary_stablecoin", sa.Text(), nullable=True),
            sa.Column("no_sanctioned_countries", sa.Boolean(), nullable=True),
            sa.Column("no_prohibited_activities", sa.Boolean(), nullable=True),
            sa.Column("has_pep", sa.Boolean(), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    # ── 4. consent_records ───────────────────────────────────────
    if not _has_table("consent_records"):
        op.create_table(
            "consent_records",
            sa.Column("id", _uuid_type(), primary_key=True),
            sa.Column(
                "user_id",
                _uuid_type(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("document_type", sa.Text(), nullable=False),
            sa.Column("document_version", sa.Text(), nullable=False),
            sa.Column(
                "accepted_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "idx_consents_user_doc_accepted",
            "consent_records",
            ["user_id", "document_type", "accepted_at"],
        )


def downgrade() -> None:
    if _has_table("consent_records"):
        op.drop_table("consent_records")
    if _has_table("company_profiles"):
        op.drop_table("company_profiles")
    for column in ("age_attested_at", "age_attested"):
        if _has_column("users", column):
            op.drop_column("users", column)
    for column in ("activation_status", "onboarding_status"):
        if _has_column("organizations", column):
            op.drop_column("organizations", column)
