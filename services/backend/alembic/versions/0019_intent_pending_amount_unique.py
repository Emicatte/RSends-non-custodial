"""Partial unique index: one pending intent per payable coordinate.

    uq_intent_pending_amount  UNIQUE (merchant_id, environment, chain,
                                      currency, amount)
                              WHERE status = 'pending'

On the router path an intent is identified exactly, by the `invoiceId` the
contract emits (`derive_invoice_id`, router_registry.py) — amount is not part of
the matching key at all. The watch-only path has no contract and no such field:
an incoming bare TRC-20 `Transfer` can only be matched on
(recipient, token, amount, time window). Two pending intents for the same
merchant, currency and amount therefore make an arriving transfer genuinely
ambiguous, and nothing in the schema forbade them — `__table_args__` carried two
NON-unique indexes and `create_intent` never queried for a collision.

THE KEY IS THE COORDINATE A PAYMENT ARRIVES AT, which is why `environment` and
`chain` are in it. Ambiguity only exists between intents an incoming transfer
could BOTH be. A `test` intent and a `live` one are never candidates for the
same transfer — every read, every write and the outbound webhook dispatch are
already filtered by `PaymentIntent.environment`, and the settlement lookup
derives the environment from the chain id (`payment_indexer._record_settlement`).
Two chains are likewise disjoint: a pending Base intent and a pending TRON
intent at the same amount are two different payments, and a TRC-20 `Transfer`
on TRON cannot possibly be the Base one. Leaving those columns out did not make
the invariant stronger, it made it wrong — it forbade pairs that are not
duplicates, including the exact pair `test_environment_filter` and
`test_list_transactions_scoped_to_environment` exist to describe.

`recipient` is deliberately NOT in the key even though the matcher keys on it:
it is nullable (split intents carry NULL and their legs live in a child table),
and in Postgres NULLs are distinct under a unique index, so including it would
silently exempt every split intent from the constraint.

That ambiguity is not currently a wrong match, it is a crash: the live lookup
uses `scalar_one_or_none()` (payment_indexer.py), which raises
`MultipleResultsFound` on a tie. This index is what turns a latent exception into
an invariant.

WHY THE INDEX IS ON THE FLOAT COLUMN, DELIBERATELY. The next reader will assume
this should have been an expression index on base units. It cannot be, and it
does not need to be.

It cannot be, because `to_base_units` (router_registry.py) is
`int((Decimal(str(x)) * 10**decimals).to_integral_value())` and no SQL expression
reproduces it:
  * `Decimal(str(x))` throws the exact binary value away and works on the
    shortest round-tripping repr, so any SQL cast that converts the true float64
    disagrees — stored 123.4567895 gives 123456790 through the Python path and
    123456789 from the exact value;
  * `.to_integral_value()` is ROUND_HALF_EVEN, while Postgres `round(numeric)` is
    half away from zero — 70000.5 is 70000 in Python and 70001 in Postgres;
  * anything routing float -> text depends on `extra_float_digits`, a
    session-settable GUC, which would also make the expression non-IMMUTABLE and
    therefore illegal in an index.

It does not need to be, because the decimal scale of `amount` is now bounded at
ingest (intent_service.create_intent, commit 645f57af, 400
AMOUNT_PRECISION_EXCEEDED): an amount finer than the token's `decimals` is
refused rather than silently rounded. So two DISTINCT accepted amounts differ by
at least one base unit, and one base unit at 6 decimals is ~5.6e8 float64 ULPs at
typical invoice sizes. The float index separates exactly the values
`to_base_units` separates. That equivalence holds up to ~9.0e9 tokens, where
float64's ULP finally exceeds one base unit — the same bound the ingest gate
has, and far above any invoice. Before that gate existed the equivalence was
false (10.0 and 10.0000001 are distinct floats and both 10000000 base units), so
the ordering of the two changes matters: this index is only correct on top of it.

SCOPE: `status = 'pending'` only. `expired` and `partial` intents are also
matcher candidates, so this does not close every ambiguous pair — it closes the
common one structurally and leaves the rest to the matcher's own `ambiguous`
outcome. Deliberately not widened: a merchant re-issuing an identical invoice
after the first expired is ordinary, and forbidding it would be a product change.

PRE-FLIGHT: violating groups are REPORTED AND THE MIGRATION STOPS, following
0014/0016/0017. Never delete, never merge, never coerce an intent row — a
duplicate here is a merchant's live invoice, and which of the two to drop is a
business decision, not a migration's.

No CONCURRENTLY: env.py runs every migration inside one transaction
(MIGRATIONS.md:50-61). OPERATOR NOTE, unlike 0017's tiny table: `payment_intents`
is hot, and MIGRATIONS.md lists "create a UNIQUE index NON-concurrently on a
hot/large table" among the things forbidden in a single release, because the
build takes a write-blocking lock. Its own mitigation applies here — run this in
a low-traffic window and accept the lock, or build the index outside Alembic and
then `alembic stamp` this revision.

Verify before running (must return zero rows):
    SELECT merchant_id, environment, chain, currency, amount, count(*)
    FROM payment_intents WHERE status = 'pending'
    GROUP BY merchant_id, environment, chain, currency, amount
    HAVING count(*) > 1;
"""

import sqlalchemy as sa

# `op` is imported lazily inside upgrade()/downgrade(), matching 0014/0016/0017:
# the project's local `alembic/` package shadows the installed library outside
# the alembic CLI runtime, and tests import revision modules by path.

# revision identifiers, used by Alembic.
# NB: id kept <=32 chars — alembic_version.version_num is VARCHAR(32). The
# filename is longer and more descriptive; Alembic keys off this string. Same
# split as 0006/0016. Pinned by test_migrations_postgres.
revision = "0019_intent_pending_unique"
down_revision = "0018_invoice_id_nullable"
branch_labels = None
depends_on = None

TABLE = "payment_intents"
INDEX = "uq_intent_pending_amount"
# The enum persists its NAME, and for IntentStatus name == value, so the stored
# string is 'pending' on both backends. Unlike 0017's boolean predicate, the
# literal needs no per-dialect variant — but both arms are still supplied,
# because the unit suite builds schema with create_all on SQLite.
PREDICATE = "status = 'pending'"


def check_pending_duplicates(bind) -> None:
    """Raise unless the uniqueness already holds on existing rows.

    Importable so tests can pin the exact behaviour without running alembic.
    Runs BEFORE any DDL and reports the offending groups so the operator can
    resolve them by hand. SELECT only — this function never writes.
    """
    rows = bind.execute(
        sa.text(
            "SELECT merchant_id, environment, chain, currency, amount, "
            "count(*) AS n "
            f"FROM {TABLE} WHERE {PREDICATE} "
            "GROUP BY merchant_id, environment, chain, currency, amount "
            "HAVING count(*) > 1 "
            "ORDER BY n DESC, merchant_id"
        )
    ).fetchall()
    if not rows:
        return

    problems = [
        f"merchant={merchant_id} [{environment}/{chain}] {currency} {amount}: "
        f"{n} pending intents"
        for merchant_id, environment, chain, currency, amount, n in rows
    ]
    raise RuntimeError(
        f"Cannot apply {revision}: {len(problems)} group(s) of pending "
        f"{TABLE} rows would violate {INDEX}. Each group is two or more live "
        "invoices a payer could pay right now, and an incoming transfer cannot "
        "tell them apart — which is the reason for the index. Do NOT delete or "
        "merge them here: choose per group which intent is real and cancel the "
        "others through the API (POST /payment-intent/{id}/cancel), or let them "
        "expire, then re-run `alembic upgrade head`. Details: "
        + "; ".join(problems)
    )


def _has_index(bind, name: str) -> bool:
    return any(ix["name"] == name for ix in sa.inspect(bind).get_indexes(TABLE))


def upgrade() -> None:
    from alembic import op

    bind = op.get_bind()

    # Report and stop before any DDL.
    check_pending_duplicates(bind)

    # Existence-guarded like 0011/0017. Load-bearing, not just hygiene: 0001 is a
    # create_all of the CURRENT model, which now declares this index, so on a
    # from-scratch `upgrade head` it already exists by the time we get here.
    # test_migrations_postgres::test_stamp_then_upgrade_is_noop enforces this.
    if not _has_index(bind, INDEX):
        op.create_index(
            INDEX,
            TABLE,
            ["merchant_id", "environment", "chain", "currency", "amount"],
            unique=True,
            postgresql_where=sa.text(PREDICATE),
            sqlite_where=sa.text(PREDICATE),
        )


def downgrade() -> None:
    from alembic import op

    bind = op.get_bind()

    if _has_index(bind, INDEX):
        op.drop_index(INDEX, table_name=TABLE)

    # No data reversal: every row that satisfies the index also satisfies the
    # unconstrained schema.
