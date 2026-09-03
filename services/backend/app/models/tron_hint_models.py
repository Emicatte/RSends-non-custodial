"""What the payer's browser told us about a transaction, and what came of it.

On a watch-only chain the poller finds payments by scanning the merchant's
address, which works and is the backstop for everything here. A hint is an
accelerator on top of it: the checkout knows the hash the moment the wallet
broadcasts, so the backend can look straight at that transaction instead of
waiting to notice it. It is never evidence. `tron_verifier` decides, on chain,
and this table only remembers the claim and the verdict.

Three states, and the middle one is the whole reason the table exists:

    pending    submitted, not yet decided — retried on every poller tick
    verified   the chain agreed; a settlement row exists because of it
    rejected   the chain disagreed, and `rejection_reason` says how

`rejected` is terminal precisely so a hash that will never verify stops costing
a node call every sixty seconds, forever.

────────────────────────────────────────────────────────────────────────
WHY THIS COLUMN IS CALLED intent_pk. READ THIS BEFORE WRITING A JOIN.
────────────────────────────────────────────────────────────────────────

`TronPaymentHint.intent_pk` is the **integer primary key** of `payment_intents`.

`PaymentIntent.intent_id` and `PaymentSettlement.intent_id` are the **string**
`"pi_…"` business id.

The column is called `intent_pk` precisely so those two can never be confused.
An earlier draft named it `intent_id`, which put three columns of the same name
and two different meanings in one subsystem: a join written from muscle memory
(`TronPaymentHint.intent_id == PaymentSettlement.intent_id`) would have compared
an integer to a string and silently matched nothing, which on SQLite and
Postgres alike is an empty result rather than an error. The name carries the
type now, so the mistake does not typecheck as prose either. Every join goes
through `PaymentIntent.id`.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)

from app.models.db_models import Base


class HintState(str, enum.Enum):
    """Lifecycle of a submitted transaction hash."""

    pending = "pending"    # not yet decided; the tick pass will ask again
    verified = "verified"  # the chain agreed, and a settlement was recorded
    rejected = "rejected"  # the chain disagreed; terminal, never re-fetched


class TronPaymentHint(Base):
    """One submitted transaction hash, and what verification made of it."""

    __tablename__ = "tron_payment_hints"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # The intent's INTERNAL integer PK — not the "pi_…" string. The `_pk`
    # suffix is load-bearing: see the module docstring.
    intent_pk = Column(
        Integer,
        ForeignKey("payment_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # TRON txids are 64 hex characters and carry no `0x`, unlike EVM. Stored
    # lowercase, and the check constraint is what keeps that true for rows
    # written by anything other than the endpoint — a hash that differs only in
    # case would defeat the unique constraint below and admit a second row for
    # the same transaction.
    tx_hash = Column(String(64), nullable=False, index=True)

    # base58check, exactly as the wallet reported it. NEVER folded: base58 is
    # case-sensitive and excludes 0 O I l, so lowercasing a T-address does not
    # tidy it, it produces a string that does not decode.
    payer_address = Column(String(34), nullable=True)

    state = Column(
        SAEnum(HintState, name="hint_state"),
        nullable=False,
        default=HintState.pending,
        server_default=HintState.pending.value,
        index=True,
    )
    # One of `tron_verifier.REJECTION_REASONS`. Free text would make the column
    # unreadable by anything but a human.
    rejection_reason = Column(String(32), nullable=True)

    submitted_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    verified_at = Column(DateTime(timezone=True), nullable=True)
    # Written on every pass whatever the outcome, so a hint that is quietly
    # stuck is visible without reading logs.
    last_checked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The idempotency of the whole feature. A payer double-clicking, a
        # client retrying, and two replicas racing all collapse into one row —
        # which is why the endpoint inserts and catches the IntegrityError
        # rather than looking first. A select-then-insert loses that race.
        UniqueConstraint("intent_pk", "tx_hash", name="uq_tron_hint_intent_tx"),
        # Lowercase, enforced by the database rather than by whoever writes
        # next. `lower(tx_hash) = tx_hash` is true for a hash with no letters
        # too, which is correct.
        CheckConstraint("tx_hash = lower(tx_hash)", name="ck_tron_hint_tx_hash_lower"),
        # The tick pass reads exactly this slice, and it is a small fraction of
        # the table once hints start resolving. Partial on both engines, the
        # same way `uq_intent_pending_amount` is.
        Index(
            "ix_tron_hint_pending",
            "intent_pk",
            postgresql_where=text("state = 'pending'"),
            sqlite_where=text("state = 'pending'"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<TronPaymentHint {self.tx_hash[:12]}… "
            f"intent_pk={self.intent_pk} state={self.state}>"
        )
