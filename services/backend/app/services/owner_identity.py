"""Owner-identity resolution for the session (org-scoped) dashboard surface.

`resolve_owner_address` maps the active org to the wallet-address tenant key
(`owner_address == ApiKey.owner_address == PaymentIntent.merchant_id ==
MerchantWebhook.merchant_id`). Precedence:

1. The org's PRIMARY EVM wallet (SIWE-verified in /settings/wallets) — always
   wins; orgs with a linked wallet resolve exactly as before the fallback.
2. The org's `settlement_wallet` — the email-onboarded merchant path — but ONLY
   if the address has no competing identity claim anywhere. Fail-closed 409
   `settlement_wallet_conflict` when the address:
   - appears in `user_wallets` for any OTHER org, INCLUDING unlinked/historical
     rows (someone else once proved control via SIWE; their data stays keyed to
     it) — EXCLUDING rows belonging to THIS org (`user_wallets.org_id ==
     org_id`): the org's own history is not a competing claim. The primary
     lookup above skips unlinked and non-primary rows, so without the carve-out
     an org that SIWE-linked its own settlement address and later unlinked it
     409s against itself on every resolve, permanently and with no in-product
     remedy (observed in production 2026-08-18). Unlinked rows are deliberately
     NOT filtered globally — a squatter's fallback must die the moment the real
     owner proves control, and stay dead if they later unlink.
   - is another org's `settlement_wallet` (the column is not unique);
   - is an `api_keys.owner_address`, active OR revoked (an rsend_ key mint
     proved control via EIP-191 signature) — EXCLUDING keys this same org
     owns (`api_keys.org_id == org_id`, migration 0011): without the
     carve-out, a settlement-wallet-fallback org's first session-minted key
     would 409 every later resolve, including its own stats/payments reads
     and the mint of key #2. Since 0014 backfilled org_id onto EVERY key,
     the carve-out also covers the org's historical wallet-minted keys —
     strictly fewer false-positive 409s; a foreign org's key still conflicts.
   All three checks exclude the resolving org itself and nothing more. The two
   over a nullable tenant column (`user_wallets.org_id`, `api_keys.org_id`)
   carry a NULL arm — `is_(None) | (… != org_id)` — because a bare `!= org_id`
   would not count a NULL-org row, opening a hole instead of closing one; the
   settlement-wallet check needs none (`Organization.id` is a PK). The checks
   re-run on every request, so a later legitimate claim (e.g. the real owner
   SIWE-links the address) immediately revokes a squatter's fallback.

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
                func.lower(UserWallet.address) == addr,
                # THIS org's own rows are its own history, not a competing
                # claim. The primary lookup above skips unlinked/non-primary
                # rows, so without the carve-out an org that SIWE-linked its
                # settlement address and later unlinked it 409s against itself
                # forever, with no in-product remedy. Mirrors `keyed` below,
                # NULL arm included — a bare `!= org_id` would not count a
                # NULL-org row (SQL three-valued logic), opening a hole
                # instead of closing one. Unlinked rows are deliberately NOT
                # filtered globally: a squatter's fallback must die the moment
                # the real owner proves control, even if they later unlink.
                (UserWallet.org_id.is_(None)) | (UserWallet.org_id != org_id),
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
                # THIS org's own keys are our identity, not a competing claim
                # (module docstring; 0011 + 0014). The NULL arm is a belt for
                # a not-yet-migrated DB — 0014 makes org_id NOT NULL.
                (ApiKey.org_id.is_(None)) | (ApiKey.org_id != org_id),
            )
        )
    ).scalar()
    if claimed or shared or keyed:
        raise HTTPException(
            status_code=409, detail={"code": "settlement_wallet_conflict"}
        )
    return addr


async def resolve_org_for_wallet(db: AsyncSession, wallet_address: str) -> str:
    """Reverse of `resolve_owner_address`: the ONE org a wallet belongs to.

    Same precedence as 0014's backfill mapping — active `user_wallets` link
    first, else `organizations.settlement_wallet`. Fail-closed 422 when the
    wallet maps to no org or to more than one (never guess key tenancy).
    Used by the legacy wallet-signed key mint to stamp `api_keys.org_id`
    (NOT NULL since 0014)."""
    addr = (wallet_address or "").lower()

    org_ids = (
        (
            await db.execute(
                select(UserWallet.org_id)
                .where(
                    func.lower(UserWallet.address) == addr,
                    UserWallet.unlinked_at.is_(None),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    if not org_ids:
        org_ids = (
            (
                await db.execute(
                    select(Organization.id).where(
                        func.lower(Organization.settlement_wallet) == addr
                    )
                )
            )
            .scalars()
            .all()
        )

    if len(org_ids) == 1:
        return str(org_ids[0])
    raise HTTPException(
        status_code=422,
        detail={
            "code": "org_unresolvable" if not org_ids else "org_ambiguous",
            "message": (
                "This wallet does not resolve to exactly one organization; "
                "link it in /settings/wallets or set it as the organization's "
                "settlement wallet, then retry."
            ),
        },
    )
