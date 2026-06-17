"""
RSends Backend — Alchemy Webhook Manager

Gestisce webhook Alchemy Address Activity via Alchemy Notify API:
  - Registra/aggiorna webhook quando l'utente crea/elimina regole
  - Aggiunge/rimuove address monitorati sul webhook
  - Sync completa di tutti gli address attivi

API Reference: https://docs.alchemy.com/reference/create-webhook

ENV necessarie:
  - ALCHEMY_AUTH_TOKEN: token per autenticazione Alchemy Notify API
  - ALCHEMY_WEBHOOK_SECRET: signing key per verificare payload in arrivo
"""

import logging
from typing import Optional

import httpx
from sqlalchemy import func, select

from app.config import get_settings
from app.db.session import async_session
from app.models.forwarding_models import ForwardingRule

logger = logging.getLogger("alchemy_webhook_manager")

ALCHEMY_API_BASE = "https://dashboard.alchemy.com/api"

NETWORK_MAP: dict[int, str] = {
    8453:  "BASE_MAINNET",
    84532: "BASE_SEPOLIA",
    1:     "ETH_MAINNET",
    42161: "ARB_MAINNET",
}


# ═══════════════════════════════════════════════════════════════
#  HTTP Helper
# ═══════════════════════════════════════════════════════════════

async def _alchemy_request(
    method: str,
    endpoint: str,
    json_data: Optional[dict] = None,
) -> Optional[dict]:
    """
    Make an authenticated request to the Alchemy Notify API.

    Returns parsed JSON on success, None on failure.
    """
    settings = get_settings()
    token = settings.alchemy_auth_token

    if not token:
        logger.debug("ALCHEMY_AUTH_TOKEN not configured — skipping API call")
        return None

    headers = {
        "X-Alchemy-Token": token,
        "Content-Type": "application/json",
    }
    url = f"{ALCHEMY_API_BASE}/{endpoint}"

    try:
        async with httpx.AsyncClient() as client:
            if method == "POST":
                resp = await client.post(
                    url, json=json_data, headers=headers, timeout=15
                )
            elif method == "PATCH":
                resp = await client.patch(
                    url, json=json_data, headers=headers, timeout=15
                )
            elif method == "GET":
                resp = await client.get(url, headers=headers, timeout=15)
            elif method == "DELETE":
                resp = await client.delete(
                    url, json=json_data, headers=headers, timeout=15
                )
            else:
                logger.error("Unknown HTTP method: %s", method)
                return None

        if resp.status_code not in (200, 201):
            logger.error(
                "[alchemy] %s %s failed: HTTP %d — %s",
                method,
                endpoint,
                resp.status_code,
                resp.text[:300],
            )
            return None

        return resp.json()

    except httpx.TimeoutException:
        logger.warning("[alchemy] %s %s timed out", method, endpoint)
        return None
    except Exception as e:
        logger.error("[alchemy] %s %s error: %s", method, endpoint, e)
        return None


# ═══════════════════════════════════════════════════════════════
#  Webhook CRUD
# ═══════════════════════════════════════════════════════════════

async def get_team_webhooks() -> list[dict]:
    """List all webhooks for the team."""
    result = await _alchemy_request("GET", "team-webhooks")
    if not result:
        return []
    return result.get("data", [])


async def find_address_activity_webhook(
    chain_id: int = 8453,
) -> Optional[dict]:
    """
    Find the existing ADDRESS_ACTIVITY webhook for the given chain.

    Returns the first active matching webhook, or None.
    """
    network = NETWORK_MAP.get(chain_id, "BASE_MAINNET")
    webhooks = await get_team_webhooks()

    for wh in webhooks:
        if (
            wh.get("webhook_type") == "ADDRESS_ACTIVITY"
            and wh.get("network") == network
            and wh.get("is_active", True)
        ):
            return wh

    return None


async def create_webhook(
    webhook_url: str,
    chain_id: int = 8453,
    addresses: Optional[list[str]] = None,
) -> Optional[dict]:
    """
    Create a new ADDRESS_ACTIVITY webhook on Alchemy.

    Args:
        webhook_url: Public URL for Alchemy to POST to
        chain_id: EVM chain ID
        addresses: Initial list of addresses to monitor
    """
    network = NETWORK_MAP.get(chain_id, "BASE_MAINNET")

    payload = {
        "network": network,
        "webhook_type": "ADDRESS_ACTIVITY",
        "webhook_url": webhook_url,
        "addresses": [a.lower() for a in (addresses or [])],
    }

    result = await _alchemy_request("POST", "create-webhook", payload)
    if result:
        webhook_id = result.get("data", {}).get("id", "?")
        logger.info(
            "[alchemy] Created webhook %s on %s with %d addresses",
            webhook_id,
            network,
            len(addresses or []),
        )
    return result


async def update_webhook_addresses(
    webhook_id: str,
    addresses_to_add: Optional[list[str]] = None,
    addresses_to_remove: Optional[list[str]] = None,
) -> Optional[dict]:
    """
    Add or remove addresses from an existing webhook.

    Args:
        webhook_id: The Alchemy webhook ID
        addresses_to_add: Addresses to start monitoring
        addresses_to_remove: Addresses to stop monitoring
    """
    to_add = [a.lower() for a in (addresses_to_add or [])]
    to_remove = [a.lower() for a in (addresses_to_remove or [])]

    if not to_add and not to_remove:
        return {"status": "no_changes"}

    payload = {
        "webhook_id": webhook_id,
        "addresses_to_add": to_add,
        "addresses_to_remove": to_remove,
    }

    result = await _alchemy_request("PATCH", "update-webhook-addresses", payload)
    if result:
        logger.info(
            "[alchemy] Webhook %s updated: +%d -%d addresses",
            webhook_id,
            len(to_add),
            len(to_remove),
        )
    return result


async def delete_webhook(webhook_id: str) -> bool:
    """Delete a webhook by ID."""
    result = await _alchemy_request(
        "DELETE", "delete-webhook", {"webhook_id": webhook_id}
    )
    if result is not None:
        logger.info("[alchemy] Deleted webhook %s", webhook_id)
        return True
    return False


# ═══════════════════════════════════════════════════════════════
#  High-level: add/remove single address
# ═══════════════════════════════════════════════════════════════

async def add_address_to_webhook(
    address: str, chain_id: int = 8453
) -> bool:
    """
    Add a single address to the Alchemy webhook.

    Called when a new forwarding rule is created.
    If no webhook exists, logs a warning (webhook must be created manually
    or via sync_monitored_addresses with a public URL).
    """
    settings = get_settings()
    if not settings.alchemy_auth_token:
        return False

    webhook = await find_address_activity_webhook(chain_id)
    if not webhook:
        logger.warning(
            "[alchemy] No webhook found for chain %d — address %s not added. "
            "Create a webhook first via the Alchemy dashboard.",
            chain_id,
            address[:10],
        )
        return False

    result = await update_webhook_addresses(
        webhook["id"], addresses_to_add=[address.lower()]
    )
    return result is not None


async def remove_address_from_webhook(
    address: str, chain_id: int = 8453
) -> bool:
    """
    Remove an address from the Alchemy webhook.

    Called when a forwarding rule is deleted. Only removes the address
    if NO other active rules on this chain monitor it.
    """
    settings = get_settings()
    if not settings.alchemy_auth_token:
        return False

    # Check if any other active rule still uses this address on this chain
    async with async_session() as db:
        count_result = await db.execute(
            select(func.count())
            .select_from(ForwardingRule)
            .where(
                ForwardingRule.source_wallet == address.lower(),
                ForwardingRule.is_active == True,   # noqa: E712
                ForwardingRule.chain_id == chain_id,
            )
        )
        remaining = count_result.scalar()

    if remaining and remaining > 0:
        logger.debug(
            "[alchemy] Address %s still used by %d active rule(s) — keeping on webhook",
            address[:10],
            remaining,
        )
        return False

    webhook = await find_address_activity_webhook(chain_id)
    if not webhook:
        return False

    result = await update_webhook_addresses(
        webhook["id"], addresses_to_remove=[address.lower()]
    )
    return result is not None


# ═══════════════════════════════════════════════════════════════
#  Full sync: align webhook addresses with active rules
# ═══════════════════════════════════════════════════════════════

async def sync_monitored_addresses(chain_id: int = 8453) -> Optional[dict]:
    """
    Sync all active rule source addresses with the Alchemy webhook.

    - If no webhook exists, logs what needs to be created
    - If webhook exists, adds missing addresses and removes stale ones

    Call this periodically or at startup to ensure consistency.
    """
    settings = get_settings()
    if not settings.alchemy_auth_token:
        logger.debug("[alchemy] No auth token — sync skipped")
        return None

    # Collect all unique source addresses from active rules
    async with async_session() as db:
        result = await db.execute(
            select(ForwardingRule.source_wallet)
            .where(
                ForwardingRule.is_active == True,   # noqa: E712
                ForwardingRule.chain_id == chain_id,
            )
            .distinct()
        )
        needed = {row[0].lower() for row in result.all()}

    if not needed:
        logger.info("[alchemy] No active rules on chain %d — nothing to sync", chain_id)
        return {"status": "no_rules", "address_count": 0}

    # Find existing webhook
    webhook = await find_address_activity_webhook(chain_id)

    if not webhook:
        network = NETWORK_MAP.get(chain_id, "BASE_MAINNET")
        logger.warning(
            "[alchemy] No ADDRESS_ACTIVITY webhook found for %s. "
            "Create one via the Alchemy dashboard pointing to your "
            "/api/v1/webhooks/alchemy endpoint. Addresses needed: %s",
            network,
            list(needed)[:5],  # Log first 5 to avoid spam
        )
        return {"status": "no_webhook", "addresses_needed": list(needed)}

    webhook_id = webhook.get("id")

    # Get current addresses on the webhook (may require fetching webhook details)
    # The team-webhooks endpoint may include addresses or we may need to
    # call get-addresses separately. Use what's available.
    current_raw = webhook.get("addresses", [])
    current = {a.lower() for a in current_raw}

    to_add = list(needed - current)
    to_remove = list(current - needed)

    if not to_add and not to_remove:
        logger.info(
            "[alchemy] Webhook %s in sync (%d addresses)",
            webhook_id,
            len(current),
        )
        return {"status": "in_sync", "address_count": len(current)}

    logger.info(
        "[alchemy] Syncing webhook %s: +%d -%d addresses",
        webhook_id,
        len(to_add),
        len(to_remove),
    )

    result = await update_webhook_addresses(webhook_id, to_add, to_remove)

    return {
        "status": "synced",
        "added": len(to_add),
        "removed": len(to_remove),
        "total": len(needed),
        "result": result,
    }
