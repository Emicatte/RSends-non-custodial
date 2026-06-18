"""Add performance indexes for high-traffic query patterns.

Additive migration — only creates new indexes, does not touch existing ones.

Skipped (already exist):
  - ix_tx_tx_hash (transaction_logs.tx_hash, unique)
  - ix_tx_fiscal_ref (transaction_logs.fiscal_ref, unique)
  - idx_ledger_account (ledger_entries.account_id + created_at)
  - idx_ledger_tx (ledger_entries.transaction_id)
  - ix_intent_merchant_status (payment_intents.merchant_id + status)
  - ix_intent_status_expires (payment_intents.status + expires_at)
  - ix_delivery_status_retry (webhook_deliveries.status + next_retry_at)

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-15
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── transaction_logs — standalone status index ─────────────
    # Existing ix_tx_status_date covers (status, tx_timestamp) but
    # status-only queries (admin dashboard counts) need a single-col idx.
    op.create_index(
        "ix_tx_log_status",
        "transaction_logs",
        ["status"],
    )

    # ── transaction_logs — recipient + received_at ─────────────
    # Covers per-recipient history queries (merchant reconciliation).
    # Note: table has 'recipient' not 'wallet_address', 'received_at' not 'created_at'.
    op.create_index(
        "ix_tx_log_recipient_received",
        "transaction_logs",
        ["recipient", "received_at"],
    )

    # ── transaction_logs — received_at (time-range scans) ──────
    op.create_index(
        "ix_tx_log_received_at",
        "transaction_logs",
        ["received_at"],
    )

    # ── payment_intents — expires_at (expiration sweep) ────────
    # Existing ix_intent_status_expires covers (status, expires_at)
    # but the expire-pending-intents job queries by expires_at alone.
    op.create_index(
        "ix_pi_expires_at",
        "payment_intents",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pi_expires_at", table_name="payment_intents")
    op.drop_index("ix_tx_log_received_at", table_name="transaction_logs")
    op.drop_index("ix_tx_log_recipient_received", table_name="transaction_logs")
    op.drop_index("ix_tx_log_status", table_name="transaction_logs")
