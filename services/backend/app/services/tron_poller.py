"""TRON watch-only poller — it SEES and RECORDS. It does not match.

Phase 1, slice 2. Pending TRON intents carry a base58 recipient and no router;
nothing on chain emits an invoiceId for them. This service asks TronGrid which
USDT TRC-20 transfers landed on those recipients and writes one
`PaymentSettlement` row per transfer, with `intent_id = NULL`.

Deciding what those rows MEAN — matching one to an intent, closing the intent,
firing the webhook — is `tron_matcher`'s job (slice 3) and appears nowhere in
this file. The tick calls it through `_run_matching_pass`, but only after the
rows are written and the cursor has advanced, and wrapped so that no matching
failure can cost an observation: a payment we failed to record is gone, while a
payment we recorded but failed to match is still on the table.

A SIBLING of `payment_indexer`, not a parameterization of it. `PaymentWatcher`
requires a router address, ticks `eth_*` every 5s against an integer block
cursor with a reorg window, and its boot guard `eth_chainId`s every chain it is
handed. None of that applies to a watch-only chain, and TRON's chain id must
therefore reach none of it — see the guardrail below.

────────────────────────────────────────────────────────────────────────
WHY THERE ARE TWO ENDPOINTS, AND WHY A POSITIONAL INDEX IS FORBIDDEN
────────────────────────────────────────────────────────────────────────

DISCOVERY is `GET /v1/accounts/{addr}/transactions/trc20`. It answers with
exactly seven keys per transfer — `transaction_id`, `token_info`,
`block_timestamp`, `from`, `to`, `type`, `value` — and therefore supplies
NEITHER of two columns that are NOT NULL on `payment_settlements`:
`log_index` and `block_number`.

The tempting fix is to derive `log_index` from the position of a transfer in
the response. It is wrong, and it loses money. Two independent reasons, both
observed on mainnet rather than reasoned about:

  1. THE CROSS-ADDRESS COLLISION (the real hazard). One transaction can pay
     several merchants. Mainnet tx 0e35a6ad2639… carries two USDT transfers to
     two different addresses; each address surfaces it under its own
     `only_to=true` poll, one transfer each. A positional index gives BOTH
     `log_index = 0`, and `uq_settlement_onchain_log (chain_id, tx_hash,
     log_index)` then swallows the second as a duplicate. That is not a
     double-book — it is a payment that silently never existed. This is not
     rare: 3 of 197 distinct transactions in one 200-event sample carried two
     or more USDT transfers.

  2. THE PAGE BOUNDARY (the rarer one). If one transaction's transfers straddle
     a `fingerprint` page, per-page numbering restarts at 0 and a later re-run
     with a different split writes a second row for the same transfer. Every
     page of a tick is therefore accumulated before anything is written — but
     note that accumulating pages does NOT fix hazard 1, which is why the
     positional scheme was abandoned entirely rather than repaired. In 275
     sampled transfers, zero transactions carried two transfers to the SAME
     address; the page boundary is the case the positional scheme handles best
     and the cross-address case is the one it handles worst.

ENRICHMENT is therefore `GET /v1/transactions/{txid}/events`, ONCE PER
TRANSACTION, which carries the real `event_index` and the `block_number`. Note
that `event_index` counts every VM event in the transaction — the sample tx
also emits a `GasFreeTransfer` at index 2 from another contract — so the
indices of the USDT transfers are neither contiguous nor zero-based nor
returned in ascending order. They are stored exactly as returned.

FAIL CLOSED. Enrichment that errors, matches nothing, or matches ambiguously
writes NO row for that transfer, and the cursor pins to the earliest such
transaction. `min_timestamp` is INCLUSIVE (verified against mainnet), so the
next tick re-observes that transaction rather than stepping over it. There is
no degraded mode and no positional fallback: a payment re-observed forever is
recoverable, a payment skipped once is not.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy import distinct, func, select

from app.config import get_settings
from app.models.indexer_models import IndexerCursor
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.security.input_validator import tron_address_to_evm_hex
from app.services.tron_chain_identity import (
    TronChainIdentityError,
    assert_tron_chain_identity,
)

logger = logging.getLogger("tron_poller")


# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

# TRON's real chain id: the last 4 bytes (2b6653dc) of the mainnet genesis
# blockID pinned in `tron_chain_identity`. Derived, not invented.
#
# ── HARD GUARDRAIL ──────────────────────────────────────────────────────
# This number must NEVER be added to `router_registry.CHAIN_IDS`,
# `chain_access.TESTNET_CHAIN_IDS`, `rpc_manager._DEFAULT_PROVIDERS`,
# `RPC_PROVIDERS_JSON`, or any `RSENDS_ROUTER_*_ADDRESSES_JSON` map. Entering a
# router map makes `start_indexer_if_needed` construct a `PaymentWatcher` for
# it, which makes `verify_chain_identity_for_boot` send `eth_chainId` to a TRON
# node and `SystemExit` the backend. TRON reaches none of that machinery.
# Pinned by `test_tron_poller.py::test_tron_chain_id_is_in_no_evm_chain_table`.
TRON_CHAIN_ID = 728126428

# TRON Nile testnet's chain id: the last 4 bytes of the Nile genesis blockID
# pinned in `tron_chain_identity`. Derived, not invented — same as mainnet's.
#
# The HARD GUARDRAIL above applies to this number identically, and with one
# extra reason to be careful: Nile IS a testnet, so `chain_access.
# TESTNET_CHAIN_IDS` looks like the natural home for it. It is not. That table
# is read by the EVM boot guard, which would `eth_chainId` a TRON node and
# SystemExit the backend. Nile's testnet-ness is carried by NAME instead, in
# `chain_access.WATCH_ONLY_TESTNET_CHAINS`.
# Pinned by `test_tron_nile.py::test_nile_chain_id_is_in_no_evm_chain_table`.
TRON_NILE_CHAIN_ID = 3448148188

USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# TronGrid's free tier is ~15 QPS, so the number of pending recipient addresses
# is the limit here, not the cadence.
TRON_POLL_INTERVAL = 60.0
TRON_PAGE_LIMIT = 200
TRON_HTTP_TIMEOUT = 15.0
TRON_MAX_PAGES = 50  # a bounded walk; a fingerprint loop must not spin forever


class TronEnrichmentError(RuntimeError):
    """A transfer could not be given its real on-chain coordinates.

    Every cause collapses here — transport failure, non-200, unparseable body,
    no matching event, more than one matching event. The caller's response is
    identical in every case: write nothing, pin the cursor, log loudly.
    """


# ═══════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════

def _configured_nodes() -> list[str]:
    """Ordered TRON node base URLs, primary first. Empty when unconfigured.

    An empty list means the poller does not start, which is not an error — the
    same shape as `start_indexer_if_needed` returning [] on empty router maps.
    """
    raw = (get_settings().tron_node_urls_json or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning(
            "[tron-poller] TRON_NODE_URLS_JSON is not valid JSON; "
            "the poller will not start"
        )
        return []
    if not isinstance(parsed, list):
        logger.warning(
            "[tron-poller] TRON_NODE_URLS_JSON must be a JSON array of node "
            "URLs; got %s. The poller will not start", type(parsed).__name__
        )
        return []
    return [u.rstrip("/") for u in parsed if isinstance(u, str) and u.strip()]


def _auth_headers() -> dict:
    key = (get_settings().trongrid_api_key or "").strip()
    return {"TRON-PRO-API-KEY": key} if key else {}


# ═══════════════════════════════════════════════════════════════
#  Cursor
# ═══════════════════════════════════════════════════════════════
#
# The cursor row is `IndexerCursor(chain_id=728126428)` and reuses the EVM
# indexer's table. Its `last_block` column holds a MILLISECOND
# `block_timestamp`, NOT a block number: the column is a BigInteger monotonic
# cursor, and this is TRON's meaning of it. TronGrid's trc20 endpoint pages by
# timestamp and never returns a block number, so a block cursor is not
# available to us even in principle.

def _now_ms() -> int:
    """Wall clock in ms. A named seam so tests can freeze it."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


async def _get_tron_cursor() -> Optional[int]:
    """Last observed `block_timestamp` in MILLISECONDS (not a block number)."""
    from app.db.session import async_session

    async with async_session() as db:
        row = (await db.execute(
            select(IndexerCursor).where(IndexerCursor.chain_id == TRON_CHAIN_ID)
        )).scalar_one_or_none()
        return int(row.last_block) if row is not None else None


async def _set_tron_cursor(timestamp_ms: int) -> None:
    """Persist the cursor. `last_block` holds MILLISECONDS, not a block number."""
    from app.db.session import async_session

    async with async_session() as db:
        row = (await db.execute(
            select(IndexerCursor).where(IndexerCursor.chain_id == TRON_CHAIN_ID)
        )).scalar_one_or_none()
        if row is None:
            db.add(IndexerCursor(
                chain_id=TRON_CHAIN_ID,
                last_block=timestamp_ms,
                updated_at=datetime.now(timezone.utc),
            ))
        else:
            row.last_block = timestamp_ms
            row.updated_at = datetime.now(timezone.utc)
        await db.commit()


# ═══════════════════════════════════════════════════════════════
#  What to watch
# ═══════════════════════════════════════════════════════════════

async def _pending_tron_recipients() -> list[str]:
    """Distinct recipients of pending TRON intents.

    `chain` is stored VERBATIM as the caller sent it — slice 1 pins the real
    value as "TRON", uppercase — so the comparison folds case in the query, the
    same idiom `payment_indexer` uses for its chain filter.
    """
    from app.db.session import async_session

    async with async_session() as db:
        rows = (await db.execute(
            select(distinct(PaymentIntent.recipient)).where(
                func.lower(PaymentIntent.chain) == "tron",
                PaymentIntent.status == IntentStatus.pending,
                PaymentIntent.recipient.isnot(None),
            )
        )).scalars().all()
    return [r for r in rows if r]


# ═══════════════════════════════════════════════════════════════
#  Pairing a transfer to its event
# ═══════════════════════════════════════════════════════════════

def _pair_transfer_to_event(transfer: dict, events: list) -> dict:
    """The one event that IS this transfer. Raise if not exactly one.

    The two endpoints disagree on address encoding — trc20 answers base58check,
    the event API answers 20-byte hex — so the transfer's addresses are decoded
    through the single base58 decoder in `input_validator` before comparison.

    Ambiguity is a failure, not a coin flip: two events matching contract,
    sender, recipient and value are genuinely indistinguishable from here, and
    picking either would assign a real payment the other one's log index.
    """
    txid = transfer.get("transaction_id")
    contract = (transfer.get("token_info") or {}).get("address")
    to_hex = tron_address_to_evm_hex(transfer.get("to"))
    from_hex = tron_address_to_evm_hex(transfer.get("from"))
    value = str(transfer.get("value"))

    if to_hex is None or from_hex is None or not contract:
        raise TronEnrichmentError(
            f"tx {txid}: transfer has an undecodable address "
            f"(from={transfer.get('from')!r} to={transfer.get('to')!r}); "
            "refusing to pair it"
        )

    candidates = []
    for ev in events or []:
        if ev.get("event_name") != "Transfer":
            continue
        if ev.get("contract_address") != contract:
            continue
        result = ev.get("result") or {}
        if str(result.get("to", "")).lower() != to_hex:
            continue
        if str(result.get("from", "")).lower() != from_hex:
            continue
        if str(result.get("value", "")) != value:
            continue
        candidates.append(ev)

    if not candidates:
        raise TronEnrichmentError(
            f"tx {txid}: no Transfer event matches the observed transfer of "
            f"{value} to {transfer.get('to')} — cannot determine its real "
            "event_index, so it will NOT be recorded"
        )
    if len(candidates) > 1:
        raise TronEnrichmentError(
            f"tx {txid}: ambiguous enrichment — {len(candidates)} Transfer "
            f"events match the transfer of {value} to {transfer.get('to')} "
            f"(event indices {[c.get('event_index') for c in candidates]}); "
            "refusing to guess which log index this payment has"
        )

    ev = candidates[0]
    try:
        int(ev["event_index"])
        int(ev["block_number"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TronEnrichmentError(
            f"tx {txid}: matched event is missing a usable event_index / "
            f"block_number ({exc!r})"
        ) from exc
    return ev


# ═══════════════════════════════════════════════════════════════
#  The write
# ═══════════════════════════════════════════════════════════════

async def _record_settlement(transfer: dict, event: dict) -> str:
    """Insert one watch-only settlement. Returns "new" or "duplicate".

    Idempotency is the read-then-branch on `uq_settlement_onchain_log` that
    `payment_indexer._record_settlement` uses, plus an `IntegrityError` catch
    the EVM path does not need: two polled addresses paid by one transaction
    are enriched from the same event list, and a retried tick can race itself.

    Addresses are written base58, UNFOLDED. Nothing in the model lowercases;
    the EVM path folds at its decoders, and this file uses none of them.
    """
    from sqlalchemy.exc import IntegrityError

    from app.db.session import async_session

    chain_id = TRON_CHAIN_ID
    tx_hash = transfer["transaction_id"]
    log_index = int(event["event_index"])

    async with async_session() as db:
        existing = (await db.execute(
            select(PaymentSettlement).where(
                PaymentSettlement.chain_id == chain_id,
                PaymentSettlement.tx_hash == tx_hash,
                PaymentSettlement.log_index == log_index,
            )
        )).scalar_one_or_none()
        if existing is not None:
            return "duplicate"

        db.add(PaymentSettlement(
            # No router, no emitted invoiceId — nullable since 0018.
            invoice_id=None,
            merchant=transfer["to"],
            payer=transfer["from"],
            token=(transfer.get("token_info") or {})["address"],
            amount=Decimal(str(transfer["value"])),
            block_timestamp=datetime.fromtimestamp(
                int(transfer["block_timestamp"]) / 1000, tz=timezone.utc
            ),
            chain_id=chain_id,
            tx_hash=tx_hash,
            log_index=log_index,
            block_number=int(event["block_number"]),
            status=SettlementStatus.pending,
            # Slice 3 matches this to an intent. Slice 2 draws no conclusion.
            intent_id=None,
        ))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return "duplicate"
    return "new"


# ═══════════════════════════════════════════════════════════════
#  The poller
# ═══════════════════════════════════════════════════════════════

async def _run_matching_pass() -> dict:
    """Run slice 3's matcher and webhook redrive. Never raises.

    Imported lazily: `tron_matcher` imports `TRON_CHAIN_ID` from here, so a
    module-level import either way round would be circular.
    """
    from app.services import tron_matcher

    try:
        counts = await tron_matcher.match_pending_tron_settlements()
        counts["redriven"] = await tron_matcher.redrive_tron_webhooks()
        return counts
    except Exception:
        logger.exception(
            "[tron-poller] matching pass failed — settlements ARE recorded and "
            "the cursor is unaffected; they will be matched on a later tick"
        )
        return {}


class TronPoller:
    """Polls TronGrid for incoming USDT TRC-20 transfers, then matches them."""

    def __init__(self, node_urls: list[str]) -> None:
        if not node_urls:
            raise ValueError("TronPoller requires at least one node URL")
        self.node_urls = list(node_urls)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    # ── HTTP, with failover across proven nodes ──────────────
    async def _get_json(self, path: str, params: dict) -> dict:
        """GET `path` from the first node that answers. Raise if none does."""
        last: Optional[Exception] = None
        for base in self.node_urls:
            url = f"{base}{path}"
            try:
                async with httpx.AsyncClient(timeout=TRON_HTTP_TIMEOUT) as client:
                    resp = await client.get(
                        url, params=params, headers=_auth_headers()
                    )
                if resp.status_code != 200:
                    last = TronEnrichmentError(
                        f"{url} answered HTTP {resp.status_code}"
                    )
                    continue
                return resp.json()
            except Exception as exc:  # transport, timeout, unparseable body
                last = exc
                continue
        raise TronEnrichmentError(f"no TRON node answered {path}: {last!r}")

    async def _fetch_transfers(self, address: str, min_timestamp: int) -> list:
        """Every incoming USDT transfer at/after `min_timestamp`, all pages.

        Pages are accumulated before anything downstream runs. `only_confirmed`
        IS the finality rule — TRON solidifies after ~19 blocks — so no
        confirmation depth is computed here or anywhere in this file.
        """
        out: list = []
        params = {
            "contract_address": USDT_TRC20_CONTRACT,
            "only_to": "true",
            "only_confirmed": "true",
            "min_timestamp": min_timestamp,
            "order_by": "block_timestamp,asc",
            "limit": TRON_PAGE_LIMIT,
        }
        path = f"/v1/accounts/{address}/transactions/trc20"
        for _ in range(TRON_MAX_PAGES):
            body = await self._get_json(path, dict(params))
            out.extend(body.get("data") or [])
            fingerprint = (body.get("meta") or {}).get("fingerprint")
            if not fingerprint:
                return out
            params["fingerprint"] = fingerprint
        logger.warning(
            "[tron-poller] %s: stopped after %d pages; more may remain",
            address, TRON_MAX_PAGES,
        )
        return out

    async def _fetch_events(self, txid: str) -> list:
        """Every event of ONE transaction — the source of the real log index."""
        body = await self._get_json(f"/v1/transactions/{txid}/events", {})
        return body.get("data") or []

    # ── one pass ─────────────────────────────────────────────
    async def _tick(self) -> dict:
        """Observe and record, then match — in that order, and isolated.

        Matching is slice 3's `tron_matcher`, deliberately run AFTER the
        settlement rows are written and after the cursor has advanced, and
        deliberately wrapped: a matching bug must never be able to prevent a
        settlement from being recorded or hold the cursor. Recording is the
        irreplaceable half — a payment we failed to observe is gone, while a
        payment we recorded but failed to match is still on the table.
        """
        observed = await self._observe()
        observed.update(await _run_matching_pass())
        return observed

    async def _observe(self) -> dict:
        cursor = await _get_tron_cursor()
        if cursor is None:
            # Cold start: anchor at now and scan nothing, the same posture the
            # EVM indexer takes at an unknown head.
            cursor = _now_ms()
            await _set_tron_cursor(cursor)
            logger.info("[tron-poller] cold start; cursor anchored at %d", cursor)
            return {"observed": 0, "written": 0, "blocked": 0}

        recipients = await _pending_tron_recipients()
        if not recipients:
            return {"observed": 0, "written": 0, "blocked": 0}

        transfers: list = []
        for address in recipients:
            transfers.extend(await self._fetch_transfers(address, cursor))
        if not transfers:
            return {"observed": 0, "written": 0, "blocked": 0}

        # ONE enrichment call per TRANSACTION, not per transfer: two merchants
        # paid by the same transaction share one event list.
        ordered_txids: list = []
        seen = set()
        for t in transfers:
            txid = t.get("transaction_id")
            if txid not in seen:
                seen.add(txid)
                ordered_txids.append(txid)

        events_by_tx: dict = {}
        unenrichable: dict = {}
        for txid in ordered_txids:
            try:
                events_by_tx[txid] = await self._fetch_events(txid)
            except Exception as exc:
                unenrichable[txid] = exc
                logger.error(
                    "[tron-poller] tx %s: enrichment call failed (%s). No "
                    "settlement will be written and the cursor will not pass "
                    "this transaction.", txid, exc,
                )

        written = 0
        blocked_at: Optional[int] = None

        def _block(ts: int) -> None:
            nonlocal blocked_at
            blocked_at = ts if blocked_at is None else min(blocked_at, ts)

        for t in sorted(transfers, key=lambda x: int(x["block_timestamp"])):
            txid = t.get("transaction_id")
            ts = int(t["block_timestamp"])
            if txid in unenrichable:
                _block(ts)
                continue
            try:
                event = _pair_transfer_to_event(t, events_by_tx.get(txid) or [])
            except TronEnrichmentError as exc:
                logger.error("[tron-poller] %s", exc)
                _block(ts)
                continue
            if await _record_settlement(t, event) == "new":
                written += 1

        # Pin TO the earliest transaction we could not enrich, never past it.
        # `min_timestamp` is inclusive, so that transaction is re-observed next
        # tick rather than skipped.
        if blocked_at is not None:
            await _set_tron_cursor(blocked_at)
            logger.warning(
                "[tron-poller] cursor held at %d: %d transaction(s) could not "
                "be enriched and their payments are NOT recorded",
                blocked_at, len(unenrichable) or 1,
            )
        else:
            await _set_tron_cursor(
                max(int(t["block_timestamp"]) for t in transfers)
            )

        return {
            "observed": len(transfers),
            "written": written,
            "blocked": 0 if blocked_at is None else 1,
        }

    # ── lifecycle ────────────────────────────────────────────
    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[tron-poller] tick failed: %s", exc)
            await asyncio.sleep(TRON_POLL_INTERVAL)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None


_poller: Optional[TronPoller] = None


async def start_tron_poller_if_needed() -> Optional[TronPoller]:
    """Prove every configured node, then start. No nodes → silently no poller.

    The identity guard runs BEFORE the cursor is read and before any TronGrid
    call, and its failure is fatal: a node that has not proven it serves TRON
    mainnet could hand us a testnet's transfers, which would be recorded as
    real payments. Starting with TRON quietly disabled is not on offer either —
    that is the silent failure this refuses.
    """
    global _poller

    nodes = _configured_nodes()
    if not nodes:
        return None

    for node_url in nodes:
        try:
            await assert_tron_chain_identity(node_url, "mainnet")
        except TronChainIdentityError as exc:
            logger.critical(
                "[tron-poller] FATAL chain identity: %s. Refusing to start — a "
                "node that has not proven it serves TRON mainnet cannot be "
                "trusted to report payments.", exc,
            )
            raise SystemExit(f"[tron-poller] FATAL {exc}") from exc

    _poller = TronPoller(node_urls=nodes)
    await _poller.start()
    logger.info(
        "[tron-poller] watching USDT TRC-20 on %d proven node(s), every %.0fs",
        len(nodes), TRON_POLL_INTERVAL,
    )
    return _poller


async def stop_tron_poller() -> None:
    global _poller
    if _poller is not None:
        await _poller.stop()
        _poller = None
