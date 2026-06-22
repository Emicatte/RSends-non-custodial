"""non-custodial baseline schema

Squashed baseline for the non-custodial RSends fork. Replaces the original 83
incremental migrations (which carried custodial ledger / sweep / KMS / forwarding
/ command-center / split / strategy tables — all removed in the fork).

This baseline creates exactly the current ORM schema via Base.metadata, so it
stays in lock-step with the SQLAlchemy models (no hand-maintained column lists).
The surviving + new tables are: users/auth/orgs, api keys, merchants + payment
intents (simplified, with onchain_invoice_id), merchant webhooks + deliveries,
invoices, AML/OFAC, notifications, the tamper-evident audit_log, user-owned
data (routes/contacts/tx/wallets), and the NEW payment_settlements table (one
row per on-chain RSendsRouter.PaymentMade event).

Revision ID: 0001_noncustodial_baseline
Revises:
Create Date: 2026-06-19
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_noncustodial_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _metadata():
    """Import the full surviving model set and return Base.metadata.

    Importing each module registers its tables on the shared declarative Base.
    Mirrors alembic/env.py and app/db/session.py — keep them in sync.
    """
    from app.models.db_models import Base  # defines Base
    from app.models import audit_models  # noqa: F401
    from app.models import settlement_models  # noqa: F401
    from app.models import aml_models  # noqa: F401
    from app.models import api_key_models  # noqa: F401
    from app.models import auth_models  # noqa: F401
    from app.models import email_auth_models  # noqa: F401
    from app.models import invoice_models  # noqa: F401
    from app.models import merchant_models  # noqa: F401
    from app.models import merchant_profile_models  # noqa: F401
    from app.models import notification_models  # noqa: F401
    from app.models import org_models  # noqa: F401
    from app.models import user_api_keys_models  # noqa: F401
    from app.models import user_contacts_models  # noqa: F401
    from app.models import user_routes_models  # noqa: F401
    from app.models import user_tx_models  # noqa: F401
    from app.models import user_wallets_models  # noqa: F401
    return Base.metadata


def upgrade() -> None:
    _metadata().create_all(bind=op.get_bind())


def downgrade() -> None:
    _metadata().drop_all(bind=op.get_bind())
