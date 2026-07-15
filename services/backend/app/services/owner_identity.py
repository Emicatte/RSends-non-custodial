"""Owner-identity resolution for the session (org-scoped) dashboard surface.

`resolve_owner_address` maps the active org to the wallet-address tenant key
(`owner_address == ApiKey.owner_address == PaymentIntent.merchant_id ==
MerchantWebhook.merchant_id`). Precedence:

1. The org's PRIMARY EVM wallet (SIWE-verified in /settings/wallets) — always
   wins; orgs with a linked wallet resolve exactly as before the fallback.
2. The org's `settlement_wallet` — the email-onboarded merchant path — but ONLY
   if the address has no competing identity claim anywhere. Fail-closed 409
   `settlement_wallet_conflict` when the address:
   - appears in `user_wallets` for ANY org, INCLUDING unlinked/historical rows
     (someone once proved control via SIWE; their data stays keyed to it);
   - is another org's `settlement_wallet` (the column is not unique);
   - is an `api_keys.owner_address`, active OR revoked (an rsend_ key mint
     proved control via EIP-191 signature) — EXCLUDING keys this same org
     minted via the session flow (`api_keys.org_id == org_id`, migration
     0011): without the carve-out, a settlement-wallet-fallback org's first
     session-minted key would 409 every later resolve, including its own
     stats/payments reads and the mint of key #2.
   The checks re-run on every request, so a later legitimate claim (e.g. the
   real owner SIWE-links the address) immediately revokes a squatter's fallback.

Neither wallet configured → 409 `no_primary_wallet` (the pre-fallback error,
kept for frontend compatibility — remedy: link a wallet or set the settlement
wallet in Settings).

Known, accepted trade-off: if a fallback-identity org later links a DIFFERENT
address as primary, the dashboard identity flips and settlement-keyed intents
drop out of view (they remain payable/settleable — checkout and indexer key by
intent). The durable fix is re-keying session tenancy on org_id.
"""

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key_models import ApiKey
from app.models.org_models import Organization
from app.models.user_wallets_models import UserWallet


async def resolve_owner_address(db: AsyncSession, org_id: str) -> str:
    """Resolve the org's owner address (lowercase) — primary EVM wallet first,
    else the unclaimed settlement_wallet. 409 fail-closed, never invented."""
    result = await db.execute(
        select(UserWallet)
        .where(
            UserWallet.org_id == org_id,
            UserWallet.is_primary.is_(True),
            UserWallet.chain_family == "evm",
            UserWallet.unlinked_at.is_(None),
        )
        .limit(1)
    )
    wallet = result.scalars().first()
    if wallet is not None:
        # address è già lowercase in DB; normalizziamo difensivamente.
        return (wallet.address or "").lower()

    settlement = (
        await db.execute(
            select(Organization.settlement_wallet).where(Organization.id == org_id)
        )
    ).scalar_one_or_none()
    if not settlement:
        raise HTTPException(status_code=409, detail={"code": "no_primary_wallet"})
    addr = settlement.lower()

    claimed = (
        await db.execute(
            select(func.count(UserWallet.id)).where(
                func.lower(UserWallet.address) == addr
            )
        )
    ).scalar()
    shared = (
        await db.execute(
            select(func.count(Organization.id)).where(
                func.lower(Organization.settlement_wallet) == addr,
                Organization.id != org_id,
            )
        )
    ).scalar()
    keyed = (
        await db.execute(
            select(func.count(ApiKey.id)).where(
                func.lower(ApiKey.owner_address) == addr,
                # Session-minted keys of THIS org are our own identity, not a
                # competing claim (see module docstring; migration 0011).
                (ApiKey.org_id.is_(None)) | (ApiKey.org_id != org_id),
            )
        )
    ).scalar()
    if claimed or shared or keyed:
        raise HTTPException(
            status_code=409, detail={"code": "settlement_wallet_conflict"}
        )
    return addr
