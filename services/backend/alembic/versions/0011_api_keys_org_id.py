"""Nullable org linkage on api_keys — session-minted rsend_ keys.

`api_keys` tenancy is keyed on `owner_address` only (custodial-era). The
session mint flow (`POST /api/v1/user/org/merchant-keys`) resolves the org's
owner address via `resolve_owner_address`, whose settlement-wallet fallback
409s when the address is already an `api_keys.owner_address` — so the org's
FIRST minted key would poison every later resolve (stats, payments, key #2).
The new nullable `org_id` lets the mint stamp its org and the conflict check
exclude the org's OWN keys. No backfill: wallet-signed keys have no org
linkage, and NULL keeps them in the conflict check exactly as before.

First contained slice of the "re-key session tenancy on org_id" follow-up.

Idempotent, existence-guarded like 0009/0010.

Revision ID: 0011_api_keys_org_id
Revises: 0010_org_approval
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0011_api_keys_org_id"
down_revision = "0010_org_approval"
branch_labels = None
depends_on = None

_INDEX = "ix_api_keys_org_id"


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return any(col["name"] == column for col in _inspector().get_columns(table))


def _has_index(table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in _inspector().get_indexes(table))


def upgrade() -> None:
    if not _has_column("api_keys", "org_id"):
        op.add_column(
            "api_keys", sa.Column("org_id", sa.String(36), nullable=True)
        )
    if not _has_index("api_keys", _INDEX):
        op.create_index(_INDEX, "api_keys", ["org_id"])


def downgrade() -> None:
    if _has_index("api_keys", _INDEX):
        op.drop_index(_INDEX, table_name="api_keys")
    if _has_column("api_keys", "org_id"):
        op.drop_column("api_keys", "org_id")
