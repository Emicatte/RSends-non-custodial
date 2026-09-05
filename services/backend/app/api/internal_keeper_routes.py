"""Internal surface: the Auto Split keeper's work list.

The keeper runs as a separate Render worker with no database credentials. It
asks this endpoint which (chain, wallet, token) tuples to preflight, and gets
back everything it cannot derive on its own.

**This read is deliberately cross-tenant.** The keeper serves every org, so
there is no org to scope by and no JWT to scope from — which makes
`INTERNAL_PROXY_SECRET` the entire security story. Two consequences, both
load-bearing:

  • The gate is on the ROUTER, not on the handler. `api_auth.py` exempts this
    prefix by `startswith`, so a second endpoint added here later inherits the
    gate instead of being born unauthenticated.

  • The prefix is in `EXEMPT_PATHS`, which means exempt from *API-key* auth, not
    unauthenticated. It has to be: `api_auth.py` consults `is_exempt` before
    anything else and is deny-by-default on every method, so a non-exempt path
    401s in the middleware and the router dependency never runs.
    `/admin/approvals` is the same shape — exempt, gated by `require_admin`.

The browser cannot reach this at all: the Next proxy denylists `api/internal`
and 404s it. The keeper calls the backend origin directly.

Read-only. No writes, ever — in particular the keeper never touches
`disabled_at`, which is the merchant's pause switch and must stay
distinguishable from an operational back-off.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_internal_secret import require_internal_secret
from app.db.session import get_db
from app.models.source_wallet_models import SourceWallet
from app.models.source_wallet_schemas import (
    KeeperSourceWallet,
    KeeperSourceWalletList,
)
from app.services.router_registry import chain_id_for, token_for
from app.services.source_wallet_service import auto_split_address_for

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/internal/keeper",
    tags=["internal-keeper"],
    dependencies=[Depends(require_internal_secret)],
)


@router.get("/source-wallets", response_model=KeeperSourceWalletList)
async def list_keeper_source_wallets(
    environment: str = Query("test", pattern="^(test|live)$"),
    db: AsyncSession = Depends(get_db),
) -> KeeperSourceWalletList:
    """Active source wallets the keeper should preflight, across all orgs.

    `disabled_at IS NULL` is the whole definition of active — there is no status
    column. Note the SESSION list route deliberately does NOT filter it (the
    dashboard shows paused rows so a merchant can see them); this one must, or
    pausing a wallet would not actually pause anything.
    """
    result = await db.execute(
        select(SourceWallet)
        .where(
            SourceWallet.environment == environment,
            SourceWallet.disabled_at.is_(None),
        )
        .order_by(SourceWallet.created_at.asc())
    )

    wallets: list[KeeperSourceWallet] = []
    for row in result.scalars().all():
        # Every one of these resolvers is fail-closed and returns None rather
        # than raising. A wallet the keeper could not act on is left OUT of the
        # work list — shipping it with a null contract address would hand the
        # keeper an address-shaped hole to send to.
        auto_split = auto_split_address_for(row.chain)
        chain_id = chain_id_for(row.chain)
        token = token_for(row.chain, row.token_symbol)
        if auto_split is None or chain_id is None or token is None:
            log.info(
                "keeper work list: skipping source wallet %s (chain=%s token=%s) — "
                "auto_split=%s chain_id=%s token=%s",
                row.id,
                row.chain,
                row.token_symbol,
                "ok" if auto_split else "unresolved",
                "ok" if chain_id else "unresolved",
                "ok" if token else "unresolved",
            )
            continue

        token_address, token_decimals = token
        wallets.append(
            KeeperSourceWallet(
                id=str(row.id),
                org_id=str(row.org_id),
                chain=row.chain,
                chain_id=chain_id,
                address=row.address,
                token_symbol=row.token_symbol,
                token_address=token_address,
                token_decimals=token_decimals,
                auto_split=auto_split,
            )
        )

    return KeeperSourceWalletList(wallets=wallets)
