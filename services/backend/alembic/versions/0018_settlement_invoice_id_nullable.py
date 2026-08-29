"""Make payment_settlements.invoice_id nullable — watch-only settlements have none.

`invoice_id` holds the bytes32 `invoiceId` that RSendsRouter emits in its
`PaymentMade` event, and the column was `String(66) NOT NULL` because on the
router path there is always exactly one. The watch-only path has no router: the
payer sends TRC-20 USDT straight to the merchant's own address and the indexer
observes a bare `Transfer`, which carries no such field. There is nothing to put
in the column.

A synthetic value is the alternative and it is worse. `payment_settlements` is
the record of what happened on-chain; writing a hash we invented into a column
whose documented meaning is "the id the contract emitted" makes the table lie
about the chain, and the lie is indistinguishable from a real id afterwards. The
matcher would also be free to key off it. NULL says the true thing: this
settlement had no on-chain invoice id.

Nothing else changes. The idempotency key is
`(chain_id, tx_hash, log_index)` (`uq_settlement_onchain_log`,
settlement_models.py:124-126) and does not involve `invoice_id`, so relaxing this
column does not weaken dedup. `ix_settlement_invoice` stays; a partial-index
narrowing is a separate decision and not this migration's business.

EXPAND step, backward-compatible per MIGRATIONS.md: relaxing NOT NULL cannot
break the old pods still serving during the rolling window, because code that
always supplies a value keeps working unchanged. The CONTRACT direction is the
dangerous one, which is why the downgrade below refuses rather than guesses.

DOWNGRADE IS NOT ALWAYS POSSIBLE, BY DESIGN. Once a watch-only settlement exists
its `invoice_id` is NULL and no value can be invented for it — there was never an
on-chain id to recover. MIGRATIONS.md separately forbids flipping a column back
to NOT NULL while running code still inserts NULLs. So the downgrade counts the
NULLs first and RAISES, naming the count, rather than backfilling a placeholder
to make the constraint fit. It restores NOT NULL only when the column is already
free of NULLs.

Existence-guarded in both directions (0011/0014/0017 house pattern): 0001 is a
`create_all` of the CURRENT model, which now declares the column nullable, so on
a from-scratch `upgrade head` the column already has its target nullability by
the time we get here. `test_migrations_postgres.py::test_stamp_then_upgrade_is_noop`
enforces that.

No CONCURRENTLY needed: this is an ALTER, not an index build. (For the record,
env.py runs every migration inside one transaction — MIGRATIONS.md:50-61 — so
CONCURRENTLY is unavailable to any revision in this chain.)

Verify after running (Postgres):
    SELECT is_nullable FROM information_schema.columns
    WHERE table_name = 'payment_settlements' AND column_name = 'invoice_id';
    -- expect: YES
"""

import sqlalchemy as sa

# `op` is imported lazily inside upgrade()/downgrade(), matching 0014/0016/0017:
# the project's local `alembic/` package shadows the installed library outside
# the alembic CLI runtime, and tests import revision modules by path.

# revision identifiers, used by Alembic.
# NB: id kept <=32 chars — alembic_version.version_num is VARCHAR(32). The
# filename is longer and more descriptive; Alembic keys off this string. Same
# split as 0006/0016. Pinned by test_migrations_postgres.
revision = "0018_invoice_id_nullable"
down_revision = "0017_user_wallets_uniques"
branch_labels = None
depends_on = None

TABLE = "payment_settlements"
COLUMN = "invoice_id"


def _invoice_id_nullable(bind) -> bool:
    """Current nullability of the column, read from the live schema.

    Mirrors `_org_id_nullable` in 0014 — the guard that makes both directions
    idempotent under stamp-then-upgrade.
    """
    cols = sa.inspect(bind).get_columns(TABLE)
    return next(c for c in cols if c["name"] == COLUMN)["nullable"]


def count_null_invoice_ids(bind) -> int:
    """How many settlements carry no on-chain invoice id.

    Importable so tests can pin the downgrade's refusal without running alembic
    (same reason 0014/0017 export their pre-flight helpers).
    """
    return bind.execute(
        sa.text(f"SELECT count(*) FROM {TABLE} WHERE {COLUMN} IS NULL")
    ).scalar_one()


def upgrade() -> None:
    from alembic import op

    bind = op.get_bind()

    if not _invoice_id_nullable(bind):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(TABLE) as batch:
                batch.alter_column(
                    COLUMN, existing_type=sa.String(66), nullable=True
                )
        else:
            op.alter_column(
                TABLE, COLUMN, existing_type=sa.String(66), nullable=True
            )


def downgrade() -> None:
    from alembic import op

    bind = op.get_bind()

    if _invoice_id_nullable(bind):
        nulls = count_null_invoice_ids(bind)
        if nulls:
            raise RuntimeError(
                f"Cannot downgrade {revision}: {nulls} row(s) in {TABLE} have "
                f"{COLUMN} IS NULL. These are watch-only settlements — the payer "
                "sent the token straight to the merchant and no contract emitted "
                "an invoiceId, so there is no value to restore and none may be "
                "invented: a placeholder here would be indistinguishable from a "
                "real on-chain id forever after. Decide what those settlements "
                "should be (delete them, or stay on this revision) and re-run. "
                "This migration will not backfill them."
            )
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(TABLE) as batch:
                batch.alter_column(
                    COLUMN, existing_type=sa.String(66), nullable=False
                )
        else:
            op.alter_column(
                TABLE, COLUMN, existing_type=sa.String(66), nullable=False
            )

    # No data reversal: every row that satisfies NOT NULL also satisfies the
    # relaxed schema, so the upgrade direction never needs undoing.
