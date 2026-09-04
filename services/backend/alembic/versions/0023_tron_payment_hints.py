"""create tron_payment_hints

    tron_payment_hints  NEW TABLE

A hint is a transaction hash reported by the payer's browser after their wallet
broadcast a TRC-20 transfer. It is NOT proof of payment and never settles
anything on its own: `tron_verifier` re-derives recipient, contract, amount,
sender and log_index from the chain, and the poller remains able to close the
intent by the ordinary amount scan if the hint is rejected. The table exists to
make settlement fast and unambiguous, not to make the frontend authoritative.

WHY A TABLE AND NOT TWO COLUMNS ON payment_intents
A payer can submit more than one hash for one intent (a first transfer that
reverted, a retry after an expiration error). Columns would hold the last one
and lose the history that explains why an intent settled the way it did.

UNIQUE (intent_pk, tx_hash) IS THE IDEMPOTENCY OF THE WHOLE FEATURE
A double-click, a client retry and two replicas racing all collapse into one
row. The endpoint inserts and catches the IntegrityError rather than reading
first — a select-then-insert loses exactly this race.

NO chain_id COLUMN, DELIBERATELY
The network is a property of the intent. A column here could disagree with it,
and a hint that claims a different chain than its own intent is a contradiction
the schema should not be able to express.

intent_pk, NOT intent_id
This holds payment_intents.id, the internal integer. PaymentIntent.intent_id and
PaymentSettlement.intent_id hold the public "pi_…" string. Three columns, one
name, two meanings — a join written from muscle memory would compare int to
string and match nothing silently, on both engines, without erroring. The `_pk`
suffix is the fix.

THE ENUM IS NATIVE
`state` is the Postgres type `hint_state`, matching SAEnum(HintState) in the
ORM. The type is created here and DROPPED in downgrade: without that drop, a
downgrade followed by an upgrade fails on CREATE TYPE, which is precisely the
cycle used to verify this file.

Existence-guarded like 0008/0011/0021/0022: 0001 is a create_all of the CURRENT
ORM, which now declares this table, so on a from-scratch `upgrade head` it
already exists by the time this runs and the guard makes this a no-op. Load
bearing, not hygiene — test_migrations_postgres::test_stamp_then_upgrade_is_noop
enforces it. The consequence worth knowing: the DDL below only ever executes on
a database that predates the model, which in practice means production and the
downgrade/upgrade cycle.

Nothing changes behaviour when this lands. Without the table, the hint endpoint
would 500 and B5 would fail; with it, both work and every path that existed
before this feature is untouched, because a hint only ever accelerates a
settlement the poller could have made anyway.

Verify after running:
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns WHERE table_name = 'tron_payment_hints';
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'tron_payment_hints'::regclass;
    SELECT indexname FROM pg_indexes WHERE tablename = 'tron_payment_hints';

Revision ID: 0023_tron_payment_hints
Revises: 0022_org_settlement_wallet_tron
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# NB: id is 23 chars — alembic_version.version_num is VARCHAR(32).
revision = "0023_tron_payment_hints"
down_revision = "0022_org_settlement_wallet_tron"
branch_labels = None
depends_on = None

TABLE = "tron_payment_hints"
ENUM_NAME = "hint_state"
STATES = ("pending", "verified", "rejected")


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table)


def _has_type(name: str) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = :n)"),
            {"n": name},
        )
    )


def upgrade() -> None:
    if _has_table(TABLE):
        return

    if not _has_type(ENUM_NAME):
        postgresql.ENUM(*STATES, name=ENUM_NAME).create(op.get_bind())

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "intent_pk",
            sa.Integer(),
            sa.ForeignKey("payment_intents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tx_hash", sa.String(64), nullable=False),
        # base58check, exactly as the wallet reported it. Never folded.
        sa.Column("payer_address", sa.String(34), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(*STATES, name=ENUM_NAME, create_type=False),
            nullable=False,
            server_default="pending",
        ),
        # One of tron_verifier.REJECTION_REASONS.
        sa.Column("rejection_reason", sa.String(32), nullable=True),
        # Application-side default only, matching the ORM: no server_default.
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("intent_pk", "tx_hash", name="uq_tron_hint_intent_tx"),
        sa.CheckConstraint(
            "tx_hash = lower(tx_hash)", name="ck_tron_hint_tx_hash_lower"
        ),
    )

    # The three index=True columns, with SQLAlchemy's own naming.
    op.create_index(f"ix_{TABLE}_intent_pk", TABLE, ["intent_pk"])
    op.create_index(f"ix_{TABLE}_tx_hash", TABLE, ["tx_hash"])
    op.create_index(f"ix_{TABLE}_state", TABLE, ["state"])

    # The tick pass reads exactly this slice.
    op.create_index(
        "ix_tron_hint_pending",
        TABLE,
        ["intent_pk"],
        postgresql_where=sa.text("state = 'pending'"),
        sqlite_where=sa.text("state = 'pending'"),
    )


def downgrade() -> None:
    if _has_table(TABLE):
        op.drop_index("ix_tron_hint_pending", table_name=TABLE)
        op.drop_index(f"ix_{TABLE}_state", table_name=TABLE)
        op.drop_index(f"ix_{TABLE}_tx_hash", table_name=TABLE)
        op.drop_index(f"ix_{TABLE}_intent_pk", table_name=TABLE)
        op.drop_table(TABLE)
    # Must go, or a subsequent upgrade fails on CREATE TYPE.
    op.execute(f"DROP TYPE IF EXISTS {ENUM_NAME}")
