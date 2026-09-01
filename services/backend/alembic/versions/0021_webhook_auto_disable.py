"""Per-endpoint failure state on merchant_webhooks — auto-disable a dead webhook.

    consecutive_permanent_failures  INTEGER     NOT NULL DEFAULT 0
    disabled_reason                 TEXT        NULL
    disabled_at                     TIMESTAMPTZ NULL

A merchant's account accumulates dead endpoints. Production currently carries
four webhook.site URLs that have been 404ing for weeks; every payment fans out to
all of them and each burns five attempts over ~2h42m of exponential backoff,
filling the logs with permanent ERRORs that mean nothing. Nobody cleans these by
hand, so the normal state of an account a few months old is mostly-dead webhooks.

Today `merchant_webhooks` cannot express any of that. Failure state lives only on
`webhook_deliveries` rows, one per (intent, event, webhook), and is never
aggregated back onto the endpoint — so nothing can answer "has this URL failed
permanently three times in a row?". `is_active` exists but has never been written
to False by any code path. These three columns are that missing state:

  * `consecutive_permanent_failures` — deliveries that exhausted their retries
    against a permanently-failed target (404, 410, DNS resolution failure,
    egress-blocked). Reset to 0 by any successful delivery, so an endpoint having
    a bad afternoon accumulates no permanent blame. Transient failures (5xx,
    timeouts, connection-refused) never touch it — the existing backoff owns those.
  * `disabled_reason` / `disabled_at` — why and when the endpoint was disabled.
    NOT optional decoration: auto-disabling silently would replace a noisy problem
    with a quiet one, and the quiet one is worse — a merchant who stops receiving
    payment notifications without knowing when it started. The dashboard shows a
    disabled endpoint AS disabled, with the reason and the date, and offers
    re-enabling. These two columns are what it reads.

NO BACKFILL, and none is needed. The defaults ARE the correct state for every
existing row: 0 permanent failures observed so far, never disabled, no reason and
no date to record. `is_active` is deliberately untouched — this migration changes
no endpoint's behaviour, it only gives the schema somewhere to record a decision
that no code makes yet. The four dead endpoints in production will disable
themselves on their next three permanent failures, once the service change lands.

NOT NULL on the counter carries `server_default="0"` so existing rows take it in
the ALTER itself rather than in a backfill pass. The default is KEPT rather than
dropped afterwards (contrast 0010, which dropped its lingering default): the model
declares the same `server_default`, so keeping it is what gives create_all parity
— env.py compares server defaults. Same shape as `environment` in 0006.

Existence-guarded like 0006/0011: 0001 is a create_all of the CURRENT ORM, which
now declares these columns, so on a from-scratch `upgrade head` they already exist
by the time this runs. Load-bearing, not hygiene —
test_migrations_postgres::test_stamp_then_upgrade_is_noop enforces it.

Downgrade drops all three, guarded, in reverse. Honest about what that loses: an
endpoint disabled before the downgrade STAYS disabled (`is_active` is not touched
here, in either direction) but loses the record of why and when, and its counter
resets. Nothing is corrupted and no endpoint silently starts or stops receiving
events — unlike 0020's narrowing, this is a reversal that can be taken.

Verify after running (three rows, then zero disabled endpoints):
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'merchant_webhooks'
      AND column_name IN ('consecutive_permanent_failures',
                          'disabled_reason', 'disabled_at')
    ORDER BY column_name;

    SELECT count(*) FROM merchant_webhooks WHERE disabled_at IS NOT NULL;

Revision ID: 0021_webhook_auto_disable
Revises: 0020_chain_id_bigint
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0021_webhook_auto_disable"
down_revision = "0020_chain_id_bigint"
branch_labels = None
depends_on = None

TABLE = "merchant_webhooks"

# Upgrade order; downgrade drops them in reverse. Each sa.Column is constructed
# inline at its add_column site rather than shared from here: attaching a Column
# binds it to a Table, and SQLAlchemy 2.0 removed Column.copy(), so a module-level
# instance cannot be reused across upgrade() and downgrade() in one process.
_COLUMN_NAMES = (
    "consecutive_permanent_failures",
    "disabled_reason",
    "disabled_at",
)


def _has_column(table: str, column: str) -> bool:
    return any(
        col["name"] == column
        for col in sa.inspect(op.get_bind()).get_columns(table)
    )


def upgrade() -> None:
    # Mirrors MerchantWebhook in app/models/merchant_models.py — the unit suite
    # builds schema with create_all on SQLite, so both places declare the same
    # thing, server_default included (env.py compares server defaults).
    if not _has_column(TABLE, "consecutive_permanent_failures"):
        op.add_column(
            TABLE,
            sa.Column(
                "consecutive_permanent_failures",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    if not _has_column(TABLE, "disabled_reason"):
        op.add_column(TABLE, sa.Column("disabled_reason", sa.Text(), nullable=True))
    if not _has_column(TABLE, "disabled_at"):
        op.add_column(
            TABLE,
            sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    for name in reversed(_COLUMN_NAMES):
        if _has_column(TABLE, name):
            op.drop_column(TABLE, name)
