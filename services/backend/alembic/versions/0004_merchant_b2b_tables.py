"""Merchant B2B tables + intent disambiguation columns.

New tables:
  - payment_intents
  - merchant_webhooks
  - webhook_deliveries

Key columns for disambiguation:
  - payment_intents.reference_id (UNIQUE, 16 hex chars) — included in TX calldata/memo
  - payment_intents.expected_sender — optional wallet address filter

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── payment_intents ──────────────────────────────────
    op.create_table(
        "payment_intents",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("intent_id", sa.String(64), unique=True, nullable=False),
        sa.Column("reference_id", sa.String(16), unique=True, nullable=False),
        sa.Column("merchant_id", sa.String(64), nullable=False),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("recipient", sa.String(42), nullable=True),
        sa.Column("network", sa.String(32), nullable=True),
        sa.Column("expected_sender", sa.String(42), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "completed", "expired", "cancelled", name="intentstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("tx_hash", sa.String(66), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_intent_intent_id", "payment_intents", ["intent_id"])
    op.create_index("ix_intent_reference_id", "payment_intents", ["reference_id"])
    op.create_index("ix_intent_merchant_id", "payment_intents", ["merchant_id"])
    op.create_index("ix_intent_tx_hash", "payment_intents", ["tx_hash"])
    op.create_index("ix_intent_merchant_status", "payment_intents", ["merchant_id", "status"])
    op.create_index("ix_intent_status_expires", "payment_intents", ["status", "expires_at"])

    # ── merchant_webhooks ────────────────────────────────
    op.create_table(
        "merchant_webhooks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(64), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("secret", sa.String(128), nullable=False),
        sa.Column("events", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_webhook_merchant_id", "merchant_webhooks", ["merchant_id"])

    # ── webhook_deliveries ───────────────────────────────
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("webhook_id", sa.Integer, sa.ForeignKey("merchant_webhooks.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), unique=True, nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "delivered", "failed", name="deliverystatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("response_code", sa.Integer, nullable=True),
        sa.Column("response_body", sa.Text, nullable=True),
        sa.Column("retries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_delivery_status_retry", "webhook_deliveries", ["status", "next_retry_at"])


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("merchant_webhooks")
    op.drop_table("payment_intents")
    op.execute("DROP TYPE IF EXISTS deliverystatus")
    op.execute("DROP TYPE IF EXISTS intentstatus")
