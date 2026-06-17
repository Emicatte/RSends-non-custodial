"""Initial double-entry bookkeeping tables.

Tabelle create:
  - accounts
  - transactions          (double-entry; != legacy transaction_logs)
  - ledger_entries
  - transaction_state_log
  - audit_log             (singolare; != audit_logs esistente per forwarding rules)

Revision ID: 0001
Revises:
Create Date: 2026-04-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = "0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── accounts ──────────────────────────────────────────────────────────
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("account_type", sa.String(64), nullable=False),
        sa.Column("address", sa.String(42), nullable=True),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── transactions ──────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("tx_type", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("tx_hash", sa.String(66), nullable=True),
        sa.Column("chain_id", sa.Integer(), nullable=True),
        sa.Column("reference", sa.String(256), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_transactions_idempotency_key"),
        sa.CheckConstraint(
            "status IN ('PENDING','AUTHORIZED','PROCESSING','COMPLETED','FAILED','REVERSED')",
            name="ck_transaction_status",
        ),
    )
    op.create_index("idx_tx_idempotency", "transactions", ["idempotency_key"])
    op.create_index("idx_tx_status", "transactions", ["status"])
    op.create_index("idx_tx_hash", "transactions", ["tx_hash"])

    # ── ledger_entries ────────────────────────────────────────────────────
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "transaction_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("entry_type", sa.String(6), nullable=False),
        # NUMERIC(28,18): mai Float per campi monetari
        sa.Column("amount", sa.Numeric(28, 18), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("balance_after", sa.Numeric(28, 18), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entry_type IN ('DEBIT','CREDIT')", name="ck_entry_type"
        ),
        sa.CheckConstraint("amount > 0", name="ck_ledger_amount_positive"),
    )
    op.create_index(
        "idx_ledger_account", "ledger_entries", ["account_id", "created_at"]
    )
    op.create_index("idx_ledger_tx", "ledger_entries", ["transaction_id"])

    # ── transaction_state_log ─────────────────────────────────────────────
    op.create_table(
        "transaction_state_log",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "transaction_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(64), nullable=True),
        sa.Column(
            "ip_address",
            postgresql.INET().with_variant(sa.String(45), "sqlite"),
            nullable=True,
        ),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_state_log_tx", "transaction_state_log", ["transaction_id"]
    )

    # ── audit_log ─────────────────────────────────────────────────────────
    # BIGSERIAL su PostgreSQL; autoincrement INTEGER su SQLite
    # Tabella "audit_log" (singolare) è diversa da "audit_logs" (plurale,
    # già esistente per il forwarding rules audit trail).
    op.create_table(
        "audit_log",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=True),
        sa.Column("actor_id", sa.String(128), nullable=True),
        sa.Column(
            "ip_address",
            postgresql.INET().with_variant(sa.String(45), "sqlite"),
            nullable=True,
        ),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "changes",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("request_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_audit_log_entity", "audit_log", ["entity_type", "entity_id"]
    )
    op.create_index("idx_audit_log_created", "audit_log", ["created_at"])


def downgrade() -> None:
    # Ordine inverso rispetto a upgrade; rispetta FK constraints:
    # ledger_entries → transactions, accounts devono essere droppate prima
    op.drop_table("audit_log")
    op.drop_table("transaction_state_log")
    op.drop_table("ledger_entries")
    op.drop_table("transactions")
    op.drop_table("accounts")
