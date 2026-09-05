"""Create source_wallets — the merchant wallets RSendsAutoSplit empties.

A "source wallet" is a wallet a merchant dedicates to receiving funds, which
the AutoSplit keeper empties on a schedule. The row is ONLY the two things the
chain cannot know:

  * the org <-> wallet linkage (on chain the merchant is just an address), and
  * the keeper's watch scope: which (chain, wallet, token) tuples to preflight,
    plus the lifecycle flag that pauses it.

The POLICY itself — recipients, bps, minAmount — is deliberately NOT mirrored
here. `RSendsAutoSplit` is ownerless and `setPolicy` is merchant-key-signed, so
a merchant can rewrite their policy without touching our API; any DB copy would
be stale the moment it was written, with no invalidation hook. `getPolicy` /
`previewSplit` are read live, and `SplitExecuted` carries a full
recipients+amounts snapshot for anyone reconstructing history.

Tenancy is `org_id` from day one, never `owner_address`. The wallet-address
tenant key on `payment_intents` / `merchant_webhooks` is custodial-era residue
tracked as the "re-key session tenancy on org_id" follow-up; a new table has no
legacy rows, so it simply does not join that debt — and it therefore never needs
`owner_identity.resolve_owner_address`, nor inherits its 409 conflict semantics.

  uq_source_wallets_active  UNIQUE (chain, address, token_symbol)
                            WHERE disabled_at IS NULL

The index is GLOBAL (cross-org), not org-scoped, and that is only safe because
registration is SIWE-verified: a row can be created only by whoever holds the
wallet's key, so the 409 it raises cannot be used to squat on an address a
competitor is about to register. (With plain address entry the same index would
import the settlement-wallet griefing class: after the first SplitExecuted the
wallet is public on chain, and anyone could claim it first. Ownership proof and
uniqueness scope are one decision, not two.)

The predicate half is what makes disable -> re-register work: without
`WHERE disabled_at IS NULL` a merchant who pauses a wallet and later resumes it
would collide with their own historical row, and the audit trail would have to
be destroyed to let them back in. Re-enable is a FRESH ROW, `user_wallets`
relink semantics.

BOTH dialect predicates are mandatory. SQLAlchemy silently DROPS a
dialect-mismatched `*_where`, so a `postgresql_where`-only index degrades to a
FULL unique index on the SQLite engine CI runs — which would forbid a merchant
from ever re-registering a disabled wallet, i.e. reject legitimate data rather
than merely under-enforce. That failure is invisible on Postgres and only shows
up in CI, or worse, in a test that never ran on SQLite. No boolean literal
appears in this predicate, so unlike 0017 there is no `true`/`1` dialect split
to carry.

The chain is keyed by NAME (`base_sepolia`, `tron_nile`), not by an EVM chain
id. Deliberate deviation from the Phase 0 spec, which said `chain_id INTEGER`,
and a correction to this revision's own first draft, which said BIGINT.

RSendsAutoSplit is no longer EVM-only: it compiles under the tronprotocol solc
fork and executes on TRON, and TRON has no EVM chain id. A numeric column can
therefore only hold a TRON chain by inventing one, which is precisely what
`router_registry._load_registry` refuses to do and says why:

    a non-EVM chain has no EVM chain id, and keying it by a synthetic number is
    exactly how a reader comes to believe it is an EVM chain.

It is also actively unsafe here. `728126428` (TRON mainnet) reaching any EVM
chain table starts a `PaymentWatcher` against a non-EVM node and `SystemExit`s
the boot — pinned by `test_tron_poller.py::test_tron_chain_id_is_in_no_evm_chain_table`.
A nullable id would dodge that but replace it with a NULL that no uniqueness
index can compare, so two TRON registrations of the same wallet would both be
"active".

The name is not a new vocabulary: `token_registry.json` already keys `tron` and
`tron_nile` by name (they carry `addressFormat: base58check`), and the money
path already stores a NAME — `payment_intents.chain` is `String(32)`, and
`uq_intent_pending_amount` keys on that string column for the same reason this
index does. A new table keying money-routing config numerically while the older
one keys by name would be the inconsistency, not this.

The EVM chain id is DERIVED where it is needed (`router_registry.chain_id_for`),
which is the honest direction: every name has at most one id, not every chain
has one at all. `TEXT` rather than `String(32)` matches this table's other
columns; the value is bounded by the registry, not by user input.

Guarded by `_has_table`: migration 0001 is a `Base.metadata.create_all` of the
CURRENT model, which now declares this table, so on a from-scratch
`alembic upgrade head` the table already exists by the time this revision runs.
Same reason 0011/0017 guard their DDL.

No CONCURRENTLY: env.py runs every migration inside one transaction
(MIGRATIONS.md), and the table starts empty.

No backfill and no pre-flight check: the table is new, so there are no existing
rows that could violate the constraints. (Contrast 0014/0016/0017, which all
report-and-stop on pre-existing data — there is nothing here to report on.)
"""

import sqlalchemy as sa

from app.models.auth_models import _UUID

# `op` is imported lazily inside upgrade()/downgrade(), matching 0014/0016/0017:
# the project's local `alembic/` package shadows the installed library outside
# the alembic CLI runtime.

# revision identifiers, used by Alembic.
# NB: id kept <=32 chars — alembic_version.version_num is VARCHAR(32).
revision = "0024_source_wallets"
down_revision = "0023_tron_payment_hints"
branch_labels = None
depends_on = None

TABLE = "source_wallets"
INDEX_ACTIVE = "uq_source_wallets_active"
INDEX_ORG = "ix_source_wallets_org_id"


def _has_table(bind) -> bool:
    return TABLE in sa.inspect(bind).get_table_names()


def _has_index(bind, name: str) -> bool:
    return any(ix["name"] == name for ix in sa.inspect(bind).get_indexes(TABLE))


def upgrade() -> None:
    from alembic import op

    bind = op.get_bind()

    if not _has_table(bind):
        op.create_table(
            TABLE,
            sa.Column("id", _UUID(), primary_key=True),
            # Tenant key. CASCADE: a deleted org takes its keeper watch rows
            # with it — a row pointing at no org would be an unattributable
            # instruction to spend keeper gas.
            sa.Column(
                "org_id",
                _UUID(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # Audit only: which member registered it. SET NULL — the wallet
            # belongs to the org and outlives the person.
            sa.Column(
                "created_by_user_id",
                _UUID(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            # Canonical registry chain NAME, never an EVM chain id. See the
            # name-keying note in the docstring.
            sa.Column("chain", sa.Text(), nullable=False),
            # Derived server-side from the chain, never client-supplied, so the
            # session surface can scope reads in SQL exactly like intents do.
            sa.Column("environment", sa.Text(), nullable=False),
            # Stored in the canonical form for its chain's address FAMILY, not
            # unconditionally lowercased. An EVM address folds to lowercase for
            # case-insensitive matching, as before; a base58check address is
            # stored byte-identical, because base58 excludes `0 O I l` and
            # folding a T-address does not merely change it — it stops
            # decoding and its checksum stops verifying. `display_address` is
            # the checksummed twin on EVM and the same string on TRON.
            # `normalize_payment_address` / `display_payment_address`
            # (app/security/input_validator.py) are the one implementation of
            # that rule; `payment_intents.recipient` already follows it.
            sa.Column("address", sa.Text(), nullable=False),
            sa.Column("display_address", sa.Text(), nullable=False),
            # Symbol only. The on-chain token ADDRESS is never stored and never
            # accepted from a client: it is resolved server-side through
            # `router_registry.token_for(chain, symbol)` at each use site, so
            # the registry stays the single source of truth for what is
            # chargeable. One row per (wallet, token) mirrors the contract's
            # own `_policies[merchant][token]` key.
            sa.Column("token_symbol", sa.Text(), nullable=False),
            sa.Column("label", sa.Text(), nullable=False, server_default=""),
            # Soft disable = keeper pause, no on-chain transaction needed.
            # (The trustless brake stays `approve(spender, 0)`; this is the
            # product-level one.) Re-enable is a fresh row.
            sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("disabled_reason", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "environment IN ('test', 'live')",
                name="ck_source_wallets_environment",
            ),
            # NO `address = lower(address)` CHECK. The first draft of this
            # revision carried one, mirroring 0023's
            # ck_tron_hint_tx_hash_lower; it is removed rather than made
            # conditional, deliberately.
            #
            # A tx hash is always hex, so folding it is always safe. An address
            # is not: this table now holds base58check addresses, which that
            # predicate would reject outright — every valid TRON registration
            # would fail on a constraint whose purpose was to catch writers who
            # FORGET to normalise.
            #
            # Conditioning it is worse than dropping it. SQL can express
            # `chain NOT IN ('tron','tron_nile') AND address = lower(address)`,
            # but it cannot express base58check — verifying one means decoding
            # base58 and re-running a double-SHA256 over the payload. So the
            # conditional form enforces nothing at all on precisely the chains
            # it was extended for, while still reading like a guarantee. A
            # constraint that silently stops applying is worse than an absent
            # one, because the next reader trusts it.
            #
            # The invariant is enforced where it can be enforced completely:
            # the request schemas are the single write path and dispatch on
            # `router_registry.chain_address_format(chain)` — the chain's own
            # declared address family — rather than guessing from the string's
            # shape. Same placement as `payment_intents.recipient`, which holds
            # both families with no such CHECK.
        )

    # Declared here AND in the model's __table_args__: `create_all` builds the
    # schema from the model (0001, and every test module), while an
    # already-migrated database only ever gets DDL from a revision. Neither is
    # redundant — that asymmetry is exactly how user_wallets lost both of its
    # unique indexes for months without anyone noticing.
    if not _has_index(bind, INDEX_ACTIVE):
        op.create_index(
            INDEX_ACTIVE,
            TABLE,
            ["chain", "address", "token_symbol"],
            unique=True,
            postgresql_where=sa.text("disabled_at IS NULL"),
            sqlite_where=sa.text("disabled_at IS NULL"),
        )

    if not _has_index(bind, INDEX_ORG):
        op.create_index(INDEX_ORG, TABLE, ["org_id"])


def downgrade() -> None:
    from alembic import op

    bind = op.get_bind()

    if not _has_table(bind):
        return

    if _has_index(bind, INDEX_ORG):
        op.drop_index(INDEX_ORG, table_name=TABLE)
    if _has_index(bind, INDEX_ACTIVE):
        op.drop_index(INDEX_ACTIVE, table_name=TABLE)

    op.drop_table(TABLE)
