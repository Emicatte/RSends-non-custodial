"""Backfill NULL payment_intents.onchain_invoice_id with the LEGACY formula.

F-3 folds the chain id into derive_invoice_id (keccak(f"{chain_id}:{ref}"))
so the same reference paid on another chain derives a different invoiceId.
Intents created after fix-A carry their id in `onchain_invoice_id` (stamped
at create; matching and /pay both prefer the stored value) — they are
unaffected. Pre-fix-A rows have the column NULL: they were already
unmatchable (NULL matches no event), but their historical /pay links
advertised the LEGACY keccak(reference_id) id via the derive fallback, which
the new formula would silently change. This migration freezes the legacy id
into the column: the row becomes matchable exactly as if fix-A had stamped
it, and the new derivation applies to new intents only.

Data-only (the column exists since the non-custodial baseline); idempotent
(only touches NULL rows); no report-and-stop needed — the legacy formula is
deterministic per row and collisions are keccak-impossible. Downgrade keeps
the backfilled ids: they are the historically-advertised values, correct in
both schemas.

Revision ID: 0015_backfill_onchain_invoice_id
Revises: 0014_api_keys_org_id_backfill
Create Date: 2026-07-20
"""

import sqlalchemy as sa

# `op` is imported lazily inside upgrade()/downgrade(): tests import this
# module for `backfill_onchain_invoice_ids`, and the project's local
# `alembic/` package shadows the installed library outside the CLI runtime.

# revision identifiers, used by Alembic.
revision = "0015_backfill_onchain_invoice_id"
down_revision = "0014_api_keys_org_id_backfill"
branch_labels = None
depends_on = None


def _legacy_invoice_id(reference_id: str) -> str:
    """The pre-F-3 derivation: keccak256 of the UTF-8 reference_id."""
    from eth_utils import keccak

    return "0x" + keccak(reference_id.encode("utf-8")).hex()


def backfill_onchain_invoice_ids(bind) -> int:
    """Stamp every NULL onchain_invoice_id with the legacy-formula id.
    Importable so tests can pin the exact behavior. Returns rows updated."""
    rows = bind.execute(
        sa.text(
            "SELECT intent_id, reference_id FROM payment_intents "
            "WHERE onchain_invoice_id IS NULL ORDER BY id"
        )
    ).fetchall()
    for intent_id, reference_id in rows:
        bind.execute(
            sa.text(
                "UPDATE payment_intents SET onchain_invoice_id = :inv "
                "WHERE intent_id = :iid"
            ),
            {"inv": _legacy_invoice_id(reference_id), "iid": intent_id},
        )
    return len(rows)


def upgrade() -> None:
    from alembic import op

    backfill_onchain_invoice_ids(op.get_bind())


def downgrade() -> None:
    # No data reversal: the backfilled ids are the historically-advertised
    # legacy values — correct in both schemas.
    pass
