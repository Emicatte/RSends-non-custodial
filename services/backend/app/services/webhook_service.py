"""
RSend Backend — Webhook Delivery Service.

Gestisce la consegna dei webhook ai merchant quando un pagamento
viene confermato, scade, o viene cancellato.

Workflow:
  1. Una TX confermata chiama match_and_complete_intent()
  2. Il servizio cerca il PaymentIntent corrispondente (amount + currency + recipient)
  3. Aggiorna lo status a "completed"
  4. Invia un webhook a tutti gli URL registrati del merchant
  5. Retry fino a 5 volte con backoff esponenziale se il webhook fallisce
  6. Ogni delivery è loggata per audit

Sicurezza:
  - Ogni webhook ha un secret per HMAC-SHA256 verification
  - Header X-RSend-Signature = HMAC(secret, raw_body)
  - Idempotency: stessa TX → un solo webhook (via idempotency_key)

Backoff schedule:
  Retry 1 → 30s, Retry 2 → 2min, Retry 3 → 8min, Retry 4 → 32min, Retry 5 → 2h
"""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_object_session

from app.models.merchant_models import (
    PaymentIntent, IntentStatus, LatePaymentPolicy,
    MerchantWebhook,
    WebhookDelivery, DeliveryStatus,
)
from app.services.router_registry import _canonical_chain, chain_id_for

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 30       # 30s * 4^retry → 30s, 2m, 8m, 32m, 2h
DELIVERY_TIMEOUT = 10.0         # httpx timeout per singolo attempt
WEBHOOK_USER_AGENT = "RSend-Webhook/1.0"

# ── Auto-disable (migration 0021) ────────────────────────────────
#
# A merchant's dead endpoints are never pruned by hand, so an account a few
# months old fans every payment out to URLs that have 404'd for weeks — five
# attempts each, ~2h42m of backoff, permanent ERRORs that mean nothing.
#
# ONLY PERMANENT failures count toward disabling: the URL does not exist and
# will not start existing. A 5xx, a timeout, a refused connection or a TLS
# failure all mean the server EXISTS and is unwell — the backoff above already
# owns those, and counting them would disable endpoints that are merely having
# a bad afternoon.
DISABLE_AFTER_PERMANENT_FAILURES = 3

# `disabled_reason` holds a STABLE CODE, never prose: the dashboard maps it to
# copy, so the wording can change or be translated without rewriting rows.
PERMANENT_HTTP_REASONS = {
    404: "endpoint_not_found_404",
    410: "endpoint_gone_410",
}
DNS_FAILURE_REASON = "dns_resolution_failed"
# Prefix for the egress-guard case. Deliberately reads as "we would not contact
# this URL" rather than "your server misbehaved" — the endpoint was never
# contacted at all, and the cause is the merchant's configuration.
EGRESS_REASON_PREFIX = "url_not_allowed:"


# ═══════════════════════════════════════════════════════════════
#  Egress / SSRF guard (Phase E)
# ═══════════════════════════════════════════════════════════════
#
# Every outbound webhook POST (real delivery AND test-fire) targets a
# merchant-supplied URL. Without a guard, a merchant could point a webhook at
# `http://169.254.169.254/…` (cloud metadata), `https://127.0.0.1`, or an
# internal host and use our server as an SSRF proxy. Phase E exposed test-fire
# to session `operator`s, widening the trigger surface, so the guard lives on
# the SHARED path here (protecting the pre-existing API-key routes too).
#
# Posture: reject non-HTTPS; reject literal private/loopback/link-local/
# reserved/multicast/non-global IPs (v4, v6, and IPv4-mapped v6); for
# hostnames, resolve and reject if ANY resolved address is in those ranges.
# A DNS-resolution FAILURE is NOT treated as forbidden — an unresolvable host
# can't reach anything internal and the POST fails on its own; this also keeps
# reserved test domains (`*.example`) working. Because validation and the
# actual httpx connect share one resolver, a host that CAN reach a private IP
# is seen as private here → caught. Re-checked immediately before each POST to
# narrow the DNS-rebinding window (see send_test_event / _attempt_delivery).


class WebhookEgressError(Exception):
    """Raised when a webhook URL is not a safe public HTTPS egress target."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _ip_is_forbidden(ip_str: str) -> bool:
    """True when an IP literal is loopback/private/link-local/reserved/
    multicast/unspecified/non-global. Unwraps IPv4-mapped IPv6 first so
    `::ffff:127.0.0.1` can't smuggle a loopback past the check."""
    ip = ipaddress.ip_address(ip_str)
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


def _loopback_host(host: str) -> bool:
    """True per host loopback: 'localhost' o IP literal 127.0.0.0/8 / ::1."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def check_webhook_egress(url: str) -> Optional[str]:
    """Return a short rejection reason if `url` is an unsafe egress target,
    else None. Never raises for DNS failure — see the posture note above.

    E2E escape: RSEND_E2E_ALLOW_LOOPBACK_WEBHOOKS=1 allows LOOPBACK targets
    only (any scheme) so the Anvil money-path E2E can deliver to its local
    receiver. Everything non-loopback keeps the full guard. validate_dev_flags
    refuses startup with this flag outside ENVIRONMENT=development/test."""
    parsed = urlparse(url)
    host = parsed.hostname
    if (
        host
        and os.getenv("RSEND_E2E_ALLOW_LOOPBACK_WEBHOOKS") == "1"
        and _loopback_host(host)
    ):
        return None
    if parsed.scheme != "https":
        return "scheme_not_https"
    if not host:
        return "no_host"

    # Host is a literal IP? Decide without DNS.
    try:
        return "private_or_reserved_ip" if _ip_is_forbidden(host) else None
    except ValueError:
        pass  # not a literal IP → resolve the hostname

    port = parsed.port or 443
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError, UnicodeError):
        return None  # unresolvable → not an SSRF vector; POST will fail naturally

    for info in infos:
        addr = info[4][0]
        try:
            if _ip_is_forbidden(addr):
                return "resolves_to_private_ip"
        except ValueError:
            continue
    return None


async def create_merchant_webhook(
    db: AsyncSession,
    *,
    merchant_id: str,
    environment: str,
    url: str,
    events: list[str],
) -> MerchantWebhook:
    """Shared webhook-registration core for BOTH the API-key and the session
    (Phase E) register routes. Egress-validates the URL, generates the HMAC
    secret, and inserts the row (flushed, not committed — the caller owns the
    transaction + audit log). Raises WebhookEgressError on an unsafe URL."""
    reason = await check_webhook_egress(url)
    if reason is not None:
        raise WebhookEgressError(reason)

    webhook = MerchantWebhook(
        merchant_id=merchant_id,
        environment=environment,
        url=url,
        secret=secrets.token_hex(32),
        events=events,
        is_active=True,
    )
    db.add(webhook)
    await db.flush()
    return webhook

# ── Matching thresholds (legacy — used by match_and_complete_intent) ─
AMOUNT_TOLERANCE_EXACT = 0.001  # 0.1% — match esatto
AMOUNT_TOLERANCE_CLOSE = 0.01   # 1% — match approssimato (gas rounding)
SCORE_MIN_THRESHOLD = 50        # Sotto questa soglia → nessun match (troppo ambiguo)

# ── Scoring weights (legacy — used by match_and_complete_intent) ─────
SCORE_AMOUNT_EXACT = 50         # Amount entro 0.1%
SCORE_AMOUNT_CLOSE = 20         # Amount entro 1%
SCORE_SENDER_MATCH = 30         # expected_sender == tx sender
SCORE_NETWORK_MATCH = 20        # network/chain match
SCORE_RECENT_5MIN = 10          # Intent creato < 5 min fa
SCORE_RECENT_30MIN = 5          # Intent creato < 30 min fa

# ── Scoring weights v2 (used by match_transaction_to_intent) ────────
V2_SCORE_MIN_THRESHOLD = 40        # Sotto questa soglia → review
V2_SCORE_AMOUNT_EXACT = 50         # Amount entro tolerance % del merchant
V2_SCORE_AMOUNT_OVERPAID = 35      # Overpayment fino a 1.5x
V2_SCORE_AMOUNT_UNDERPAID = 20     # Underpayment (>= 50%)
V2_SCORE_AMOUNT_EXTREME_OVER = 5   # Overpayment > 1.5x
V2_SCORE_SENDER_MATCH = 30         # expected_sender == tx sender
V2_SCORE_SENDER_MISMATCH = -15     # expected_sender != tx sender (penalità, non skip)
V2_SCORE_NETWORK_MATCH = 15        # network/chain match
V2_SCORE_RECENT_5MIN = 10          # Intent creato < 5 min fa
V2_SCORE_RECENT_30MIN = 5          # Intent creato < 30 min fa
V2_SCORE_OLD_24H = -5              # Intent > 24h (penalità)
V2_SCORE_LATE_PENALTY = -10        # Intent scaduto (penalità)

# ── Chain ID → Network mapping ──────────────────────────────
CHAIN_NETWORK_MAP = {
    8453: "BASE_MAINNET", 84532: "BASE_SEPOLIA",
    1: "ETH_MAINNET", 42161: "ARBITRUM_MAINNET",
}


# ═══════════════════════════════════════════════════════════════
#  HMAC Signing — il merchant verifica con il SUO secret per-merchant
#  (MerchantWebhook.secret). Schema Stripe-style, replay-resistant.
#
#  Header inviati su OGNI webhook outbound:
#    X-RSend-Timestamp : unix seconds (int as string) dell'attempt
#    X-RSend-Signature : HMAC-SHA256(secret, f"{timestamp}.{raw_body}") hex
#
#  Il merchant (e i test) verificano con verify_webhook_signature():
#    constant-time compare + freshness window (anti-replay).
#
#  NB: questo è l'UNICO firmatario outbound. Non usa MAI il secret globale
#  inbound né il placeholder di verifica inbound (vedi app/services/hmac_*).
#  Il test test_webhook_signing verifica staticamente questa separazione.
# ═══════════════════════════════════════════════════════════════

WEBHOOK_SIGNATURE_HEADER = "X-RSend-Signature"
WEBHOOK_TIMESTAMP_HEADER = "X-RSend-Timestamp"
WEBHOOK_FRESHNESS_SECONDS = 300  # anti-replay window per la verifica merchant


def compute_webhook_signature(secret: str, timestamp: str, payload_bytes: bytes) -> str:
    """Compute HMAC-SHA256(secret, f"{timestamp}.{raw_body}") → hex string.

    Stripe-style: la firma copre sia il timestamp che il corpo esatto inviato,
    così la verifica può imporre una finestra di freschezza (anti-replay) e
    rilevare manomissioni sia del body che del timestamp.

    Args:
        secret: il secret per-merchant (MerchantWebhook.secret).
        timestamp: unix seconds come stringa (lo stesso valore inviato
            nell'header X-RSend-Timestamp).
        payload_bytes: i byte ESATTI del corpo HTTP inviato.
    """
    signed = timestamp.encode("utf-8") + b"." + payload_bytes
    return hmac.new(
        secret.encode("utf-8"),
        signed,
        hashlib.sha256,
    ).hexdigest()


def verify_webhook_signature(
    secret: str,
    timestamp: str,
    raw_body: bytes,
    signature: str,
    *,
    tolerance: int = WEBHOOK_FRESHNESS_SECONDS,
) -> bool:
    """Verifica una firma webhook outbound (routine di riferimento per merchant e test).

    Passi:
      1. Parse del timestamp (unix seconds). Formato invalido → reject.
      2. Freshness: rifiuta se |now - timestamp| > tolerance (anti-replay).
      3. Ricalcola HMAC-SHA256(secret, f"{timestamp}.{raw_body}") e confronta
         con hmac.compare_digest (constant-time).

    Args:
        secret: il secret per-merchant ricevuto a onboarding.
        timestamp: valore dell'header X-RSend-Timestamp.
        raw_body: i byte ESATTI del corpo ricevuto (non re-serializzati).
        signature: valore dell'header X-RSend-Signature.
        tolerance: ampiezza della finestra di freschezza in secondi.

    Returns:
        True se la firma è valida e fresca, False altrimenti.
    """
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - ts) > tolerance:
        return False

    expected = compute_webhook_signature(secret, timestamp, raw_body)
    return hmac.compare_digest(signature, expected)


# ═══════════════════════════════════════════════════════════════
#  Reference ID extraction — cerca il reference_id nel calldata
# ═══════════════════════════════════════════════════════════════

# Pattern: 16 caratteri hex alla fine del calldata (il frontend lo appende)
_REF_ID_PATTERN = re.compile(r"([0-9a-f]{16})$", re.IGNORECASE)


def try_extract_reference_id(tx_data: str) -> Optional[str]:
    """
    Cerca un reference_id (16 hex chars) nel calldata/memo della TX.

    Il reference_id viene appendato alla fine del calldata dal frontend.
    Returns None se non trovato o tx_data è vuoto.
    """
    if not tx_data:
        return None
    cleaned = tx_data.strip()
    # Rimuovi il prefisso 0x se presente per cercare nel raw hex
    if cleaned.startswith("0x") or cleaned.startswith("0X"):
        cleaned = cleaned[2:]
    match = _REF_ID_PATTERN.search(cleaned.lower())
    return match.group(1) if match else None


# ═══════════════════════════════════════════════════════════════
#  Late Payment Policy Handler
# ═══════════════════════════════════════════════════════════════

async def _handle_late_payment(
    db: AsyncSession,
    intent: PaymentIntent,
    *,
    tx_hash: str,
    now: datetime,
) -> str:
    """
    Controlla se un intent matchato è scaduto e applica la late payment policy.

    Returns:
        "ok"     — intent non scaduto, procedi normalmente
        "auto"   — intent scaduto, policy=auto, procedi con flag late
        "reject" — intent scaduto, policy=reject, non completare
        "review" — intent scaduto, policy=review, serve review manuale
    """
    if not intent.expires_at or intent.expires_at >= now:
        return "ok"

    policy = intent.late_payment_policy or LatePaymentPolicy.AUTO_COMPLETE.value
    late_mins = int((now - intent.expires_at).total_seconds() / 60)

    if policy == LatePaymentPolicy.REJECT.value:
        logger.info(
            "[Match] Intent %s expired %d min ago — REJECTED (policy=reject)",
            intent.intent_id, late_mins,
        )
        await _dispatch_event(
            db,
            merchant_id=intent.merchant_id,
            event_type="payment.expired_rejected",
            intent=intent,
            extra_payload={"tx_hash": tx_hash, "late_minutes": late_mins},
        )
        return "reject"

    elif policy == LatePaymentPolicy.REVIEW.value:
        logger.info(
            "[Match] Intent %s expired %d min ago — NEEDS REVIEW (policy=review)",
            intent.intent_id, late_mins,
        )
        intent.status = IntentStatus.review
        intent.completed_late = True
        intent.late_minutes = late_mins
        intent.tx_hash = tx_hash
        await _dispatch_event(
            db,
            merchant_id=intent.merchant_id,
            event_type="payment.needs_review",
            intent=intent,
        )
        await db.flush()
        return "review"

    else:  # auto
        logger.info(
            "[Match] Intent %s expired %d min ago — AUTO-COMPLETING (policy=auto)",
            intent.intent_id, late_mins,
        )
        intent.completed_late = True
        intent.late_minutes = late_mins
        return "auto"


# ═══════════════════════════════════════════════════════════════
#  1. Match & Complete — chiamato quando una TX viene confermata
# ═══════════════════════════════════════════════════════════════

async def match_and_complete_intent(
    db: AsyncSession,
    *,
    tx_hash: str,
    amount: float,
    currency: str,
    recipient: str,
    network: Optional[str] = None,
    sender: Optional[str] = None,
    chain_id: Optional[int] = None,
    tx_data: Optional[str] = None,
) -> Optional[PaymentIntent]:
    """
    Match una TX on-chain al PaymentIntent più probabile.

    3-tier matching:
      1. reference_id esatto (estratto da tx_data/calldata) → zero ambiguità
      2. Scoring multi-criterio (amount, sender, network, recenza) → best match
      3. Nessun match se score < SCORE_MIN_THRESHOLD → meglio non matchare

    I parametri sender, chain_id, tx_data sono opzionali per backward
    compatibility — se non forniti, il matching usa solo amount+currency+recipient.

    Returns:
        Il PaymentIntent completato, o None se nessun match abbastanza sicuro.
    """
    now = datetime.now(timezone.utc)

    # ── TIER 1: Match esatto per reference_id ────────────
    ref_id = try_extract_reference_id(tx_data or "")
    if ref_id:
        result = await db.execute(
            select(PaymentIntent).where(
                and_(
                    PaymentIntent.reference_id == ref_id,
                    PaymentIntent.status.in_([IntentStatus.pending, IntentStatus.expired]),
                )
            )
        )
        intent = result.scalar_one_or_none()
        if intent is not None:
            # Check late payment policy
            late_action = await _handle_late_payment(db, intent, tx_hash=tx_hash, now=now)
            if late_action in ("reject", "review"):
                return None

            logger.info(
                "TIER-1 match: reference_id=%s → intent=%s (tx=%s%s)",
                ref_id, intent.intent_id, tx_hash[:16],
                ", LATE" if intent.completed_late else "",
            )
            return await _complete_intent(
                db, intent, tx_hash=tx_hash, match_method="reference_id",
                match_score=100,
            )
        else:
            logger.warning(
                "reference_id=%s found in tx_data but no pending/expired intent matches",
                ref_id,
            )

    # ── TIER 2: Query candidati + scoring ────────────────
    filters = [
        PaymentIntent.status.in_([IntentStatus.pending, IntentStatus.expired]),
        PaymentIntent.currency == currency.upper(),
    ]
    if recipient:
        # EVM-only: .lower() corrupts a base58check address (base58 has no 0 O I l),
        # so this matches zero rows for a TRON recipient. Do NOT wire for watch-only.
        filters.append(PaymentIntent.recipient == recipient.lower())

    result = await db.execute(
        select(PaymentIntent).where(and_(*filters))
    )
    candidates = result.scalars().all()

    if not candidates:
        logger.debug(
            "No candidate intents for currency=%s recipient=%s",
            currency, recipient,
        )
        return None

    # ── Scoring ──────────────────────────────────────────
    best_intent: Optional[PaymentIntent] = None
    best_score = 0

    for candidate in candidates:
        # Check late payment policy prima dello scoring
        late_action = await _handle_late_payment(db, candidate, tx_hash=tx_hash, now=now)
        if late_action in ("reject", "review"):
            continue

        score = 0

        # Amount match (tolleranza per rounding gas/fee)
        if candidate.amount > 0:
            amount_diff = abs(candidate.amount - amount) / candidate.amount
        else:
            amount_diff = abs(candidate.amount - amount)

        if amount_diff < AMOUNT_TOLERANCE_EXACT:
            score += SCORE_AMOUNT_EXACT
        elif amount_diff < AMOUNT_TOLERANCE_CLOSE:
            score += SCORE_AMOUNT_CLOSE

        # Network/chain match
        if network and candidate.network and candidate.network.upper() == network.upper():
            score += SCORE_NETWORK_MATCH
        elif chain_id and candidate.network:
            # Mapping noti chain_id → network name per confronto
            chain_network_map = {
                8453: "BASE_MAINNET", 84532: "BASE_SEPOLIA",
                1: "ETH_MAINNET", 42161: "ARBITRUM_MAINNET",
            }
            if chain_network_map.get(chain_id, "").upper() == candidate.network.upper():
                score += SCORE_NETWORK_MATCH

        # Expected sender match
        if candidate.expected_sender and sender:
            if candidate.expected_sender.lower() == sender.lower():
                score += SCORE_SENDER_MATCH
            else:
                # Intent aspetta un sender specifico e non corrisponde → skip
                logger.debug(
                    "Skipping intent %s: expected_sender=%s but tx sender=%s",
                    candidate.intent_id, candidate.expected_sender, sender,
                )
                continue

        # Recenza — intent più recenti hanno priorità marginale
        age_seconds = (now - candidate.created_at).total_seconds()
        if age_seconds < 300:       # < 5 min
            score += SCORE_RECENT_5MIN
        elif age_seconds < 1800:    # < 30 min
            score += SCORE_RECENT_30MIN

        if score > best_score:
            best_score = score
            best_intent = candidate

    # ── Soglia minima ────────────────────────────────────
    if best_score < SCORE_MIN_THRESHOLD:
        logger.warning(
            "Low confidence match (score=%d, threshold=%d) for TX %s "
            "— not matching to avoid mis-attribution. Candidates: %d",
            best_score, SCORE_MIN_THRESHOLD, tx_hash[:16], len(candidates),
        )
        return None

    if best_intent is None:
        return None

    logger.info(
        "TIER-2 match: score=%d → intent=%s (tx=%s, candidates=%d)",
        best_score, best_intent.intent_id, tx_hash[:16], len(candidates),
    )
    return await _complete_intent(
        db, best_intent, tx_hash=tx_hash, match_method="scoring",
        match_score=best_score,
    )


async def _complete_intent(
    db: AsyncSession,
    intent: PaymentIntent,
    *,
    tx_hash: str,
    match_method: str,
    match_score: int,
) -> PaymentIntent:
    """
    Aggiorna un PaymentIntent a completed e triggera i webhook.

    Funzione interna usata da entrambi i tier di matching.
    """
    now = datetime.now(timezone.utc)

    intent.status = IntentStatus.completed
    intent.tx_hash = tx_hash
    intent.completed_at = now

    await db.flush()

    logger.info(
        "PaymentIntent %s completed (tx=%s, method=%s, score=%d)",
        intent.intent_id, tx_hash[:16], match_method, match_score,
    )

    # ── Triggera webhook ─────────────────────────────────
    event_type = _finalize_event_type(intent)
    await _dispatch_event(
        db,
        merchant_id=intent.merchant_id,
        event_type=event_type,
        intent=intent,
    )

    return intent


# ═══════════════════════════════════════════════════════════════
#  1b. Match Transaction v2 — 5 bug fixes integrated
#      (additive: match_and_complete_intent resta invariata)
# ═══════════════════════════════════════════════════════════════

async def match_transaction_to_intent(
    db: AsyncSession,
    *,
    tx_hash: str,
    amount: float,
    currency: str,
    recipient: str,
    network: Optional[str] = None,
    sender: Optional[str] = None,
    chain_id: Optional[int] = None,
    tx_data: Optional[str] = None,
) -> dict:
    """
    Match una TX on-chain al PaymentIntent più probabile (v2).

    5 bug fixes integrati:
      Bug 1 — reference_id è un bonus (fast-path), NON un requisito.
              Il sistema funziona anche senza reference_id nel calldata.
      Bug 2 — Tie a pari score → status "ambiguous", non FIFO.
      Bug 3 — expected_sender mismatch → penalità (-15), non skip.
      Bug 4 — Amount tolerance configurabile + under/overpayment ranges.
      Bug 5 — reference_id ownership: recipient TX deve corrispondere.

    Returns dict:
      {"status": "matched",   "intent": PaymentIntent, "match_score": int, "match_method": str, "flags": list}
      {"status": "ambiguous",  "candidates": [...], "reason": str}
      {"status": "no_match",   "reason": str}
      {"status": "review",     "intent": PaymentIntent, "reason": str}

    Dopo un "matched", il chiamante deve invocare finalize_match() per
    aggiornare lo status in base all'importo effettivamente ricevuto.
    """
    now = datetime.now(timezone.utc)

    # ── FAST PATH: reference_id match (Bug 1: bonus, non requisito) ──
    ref_id = try_extract_reference_id(tx_data or "")
    if ref_id:
        result = await db.execute(
            select(PaymentIntent).where(
                and_(
                    PaymentIntent.reference_id == ref_id,
                    PaymentIntent.status.in_([
                        IntentStatus.pending,
                        IntentStatus.expired,
                        IntentStatus.partial,
                    ]),
                )
            )
        )
        intent = result.scalar_one_or_none()
        if intent is not None:
            # Bug 5: ownership check — recipient della TX deve corrispondere
            if (
                intent.recipient
                and recipient
                and intent.recipient.lower() != recipient.lower()
            ):
                logger.warning(
                    "[Match-v2] reference_id %s found but recipient mismatch: "
                    "intent=%s, tx=%s — possible hijack, falling through to scoring",
                    ref_id, intent.recipient, recipient,
                )
                # Fall through to scoring — non matchare per reference_id
            else:
                # Check late payment policy
                late_action = await _handle_late_payment(
                    db, intent, tx_hash=tx_hash, now=now,
                )
                if late_action == "reject":
                    return {
                        "status": "no_match",
                        "reason": f"Intent {intent.intent_id} expired, policy=reject",
                    }
                if late_action == "review":
                    return {
                        "status": "review",
                        "intent": intent,
                        "reason": "Late payment needs manual review (policy=review)",
                    }

                logger.info(
                    "TIER-1 match (v2): reference_id=%s → intent=%s (tx=%s%s)",
                    ref_id, intent.intent_id, tx_hash[:16],
                    ", LATE" if intent.completed_late else "",
                )
                return {
                    "status": "matched",
                    "intent": intent,
                    "match_score": 100,
                    "match_method": "reference_id",
                    "flags": [],
                }
        else:
            logger.warning(
                "reference_id=%s found in tx_data but no pending/expired/partial intent matches",
                ref_id,
            )

    # ── TIER 2: Query candidati + scoring ────────────────
    filters = [
        PaymentIntent.status.in_([
            IntentStatus.pending,
            IntentStatus.expired,
            IntentStatus.partial,
        ]),
        PaymentIntent.currency == currency.upper(),
    ]
    if recipient:
        # EVM-only: .lower() corrupts a base58check address (base58 has no 0 O I l),
        # so this matches zero rows for a TRON recipient. Do NOT wire for watch-only.
        filters.append(PaymentIntent.recipient == recipient.lower())

    result = await db.execute(
        select(PaymentIntent).where(and_(*filters))
    )
    candidates = result.scalars().all()

    if not candidates:
        return {
            "status": "no_match",
            "reason": f"No pending intents for currency={currency} recipient={recipient}",
        }

    # ── Scoring ──────────────────────────────────────────
    scored: list[tuple[int, PaymentIntent, list[str]]] = []

    for candidate in candidates:
        score = 0
        flags: list[str] = []

        # -- Expiry check (soft penalty) --
        is_expired = candidate.expires_at and candidate.expires_at < now
        if is_expired:
            late_mins = int((now - candidate.expires_at).total_seconds() / 60)
            if candidate.late_payment_policy == LatePaymentPolicy.REJECT.value:
                continue  # Skip entirely — policy is reject
            flags.append(f"late:{late_mins}min")
            score += V2_SCORE_LATE_PENALTY  # -10

        # -- Amount match (Bug 4: tolerance + under/over ranges) --
        intent_amount = float(candidate.amount)
        if intent_amount > 0:
            ratio = amount / intent_amount
            tolerance = (candidate.amount_tolerance_percent or 1.0) / 100.0

            if (1 - tolerance) <= ratio <= (1 + tolerance):
                score += V2_SCORE_AMOUNT_EXACT          # +50
            elif (1 + tolerance) < ratio <= 1.5:
                score += V2_SCORE_AMOUNT_OVERPAID       # +35
                flags.append(f"overpaid:{ratio:.2f}x")
            elif 0.5 <= ratio < (1 - tolerance):
                score += V2_SCORE_AMOUNT_UNDERPAID      # +20
                flags.append(f"underpaid:{ratio:.2f}x")
            elif ratio > 1.5:
                score += V2_SCORE_AMOUNT_EXTREME_OVER   # +5
                flags.append(f"overpaid_extreme:{ratio:.2f}x")
            else:
                # Meno del 50% — quasi certamente non è questo intent
                continue

        # -- Network/chain match --
        if network and candidate.network and candidate.network.upper() == network.upper():
            score += V2_SCORE_NETWORK_MATCH  # +15
        elif chain_id and candidate.network:
            if CHAIN_NETWORK_MAP.get(chain_id, "").upper() == candidate.network.upper():
                score += V2_SCORE_NETWORK_MATCH  # +15

        # -- Sender match (Bug 3: penalità, non skip) --
        if candidate.expected_sender:
            if sender and candidate.expected_sender.lower() == sender.lower():
                score += V2_SCORE_SENDER_MATCH       # +30
            else:
                score += V2_SCORE_SENDER_MISMATCH    # -15
                flags.append("sender_mismatch")

        # -- Recenza --
        age_minutes = (now - candidate.created_at).total_seconds() / 60
        if age_minutes < 5:
            score += V2_SCORE_RECENT_5MIN    # +10
        elif age_minutes < 30:
            score += V2_SCORE_RECENT_30MIN   # +5
        elif age_minutes > 1440:             # > 24h
            score += V2_SCORE_OLD_24H        # -5

        scored.append((score, candidate, flags))

    if not scored:
        return {
            "status": "no_match",
            "reason": "No viable candidates after scoring",
        }

    # ── Ordina per score decrescente ──
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_intent, best_flags = scored[0]

    # ── Bug 2: Tie detection → ambiguous ──
    if len(scored) >= 2:
        second_score = scored[1][0]
        if best_score == second_score:
            tied_count = len([s for s in scored if s[0] == best_score])
            logger.warning(
                "[Match-v2] TIE at score %d between %d intents for TX %s — ambiguous",
                best_score, tied_count, tx_hash[:16],
            )
            return {
                "status": "ambiguous",
                "candidates": [
                    {
                        "intent_id": s[1].intent_id,
                        "score": s[0],
                        "flags": s[2],
                        "merchant_id": s[1].merchant_id,
                        "amount": str(s[1].amount),
                    }
                    for s in scored[:5]  # Max 5 candidati
                ],
                "reason": f"Tie at score {best_score} between {tied_count} intents",
            }

    # ── Soglia minima → review ──
    if best_score < V2_SCORE_MIN_THRESHOLD:
        logger.warning(
            "[Match-v2] Low confidence (score=%d, threshold=%d) for TX %s — review",
            best_score, V2_SCORE_MIN_THRESHOLD, tx_hash[:16],
        )
        return {
            "status": "review",
            "intent": best_intent,
            "reason": f"Low confidence match (score={best_score}, flags={best_flags})",
        }

    # ── Check flags che richiedono review ──
    needs_review = any(
        f.startswith("sender_mismatch")
        or f.startswith("underpaid")
        or f.startswith("overpaid_extreme")
        or f.startswith("late:")
        for f in best_flags
    )

    if needs_review:
        logger.info(
            "[Match-v2] TIER-2 match with review flags: score=%d, flags=%s → intent=%s",
            best_score, best_flags, best_intent.intent_id,
        )
        return {
            "status": "review",
            "intent": best_intent,
            "reason": f"Match with flags: {best_flags}",
        }

    # ── Match pulito ──
    logger.info(
        "[Match-v2] TIER-2 match: score=%d → intent=%s (tx=%s, candidates=%d)",
        best_score, best_intent.intent_id, tx_hash[:16], len(candidates),
    )
    return {
        "status": "matched",
        "intent": best_intent,
        "match_score": best_score,
        "match_method": "scoring",
        "flags": best_flags,
    }


# ═══════════════════════════════════════════════════════════════
#  1c. Finalize Match — aggiorna status in base all'importo
# ═══════════════════════════════════════════════════════════════

async def finalize_match(
    db: AsyncSession,
    intent: PaymentIntent,
    *,
    actual_amount: float,
    tx_hash: str,
) -> PaymentIntent:
    """
    Post-match finalization: aggiorna lo stato del PaymentIntent in base
    all'importo effettivamente ricevuto vs atteso.

    Gestisce:
      - Match esatto (entro tolerance) → completed
      - Overpayment → overpaid (se allow_overpayment) o review
      - Underpayment (>= 50%) → partial (se allow_partial) o review
      - Underpayment estremo (< 50%) → review
    """
    expected = float(intent.amount)
    tolerance = (intent.amount_tolerance_percent or 1.0) / 100.0
    ratio = actual_amount / expected if expected > 0 else 0
    now = datetime.now(timezone.utc)

    intent.amount_received = str(actual_amount)
    intent.tx_hash = tx_hash
    intent.completed_at = now

    if (1 - tolerance) <= ratio <= (1 + tolerance):
        # Match esatto (entro tolerance)
        intent.status = IntentStatus.completed

    elif ratio > (1 + tolerance):
        # Overpayment
        overpaid = actual_amount - expected
        intent.overpaid_amount = str(overpaid)
        if intent.allow_overpayment:
            intent.status = IntentStatus.overpaid
        else:
            intent.status = IntentStatus.review

    elif ratio < (1 - tolerance) and ratio >= 0.5:
        # Underpayment (almeno 50%)
        underpaid = expected - actual_amount
        intent.underpaid_amount = str(underpaid)
        if intent.allow_partial:
            intent.status = IntentStatus.partial
        else:
            intent.status = IntentStatus.review

    else:
        # < 50% dell'importo — probabilmente errore
        intent.status = IntentStatus.review

    await db.flush()

    # Webhook al merchant
    event_type = _finalize_event_type(intent)

    logger.info(
        "PaymentIntent %s finalized: status=%s (expected=%.6f, received=%.6f, "
        "ratio=%.2f, tx=%s)",
        intent.intent_id, intent.status.value,
        expected, actual_amount, ratio, tx_hash[:16],
    )

    await _dispatch_event(
        db,
        merchant_id=intent.merchant_id,
        event_type=event_type,
        intent=intent,
        extra_payload={
            "expected_amount": str(expected),
            "received_amount": str(actual_amount),
            "overpaid_amount": intent.overpaid_amount,
            "underpaid_amount": intent.underpaid_amount,
        },
    )

    return intent


# ═══════════════════════════════════════════════════════════════
#  2. Expire Intents — chiamato periodicamente (Celery beat)
# ═══════════════════════════════════════════════════════════════

async def expire_stale_intents(db: AsyncSession) -> int:
    """Segna come expired tutti gli intent pending scaduti. Ritorna il count.

    B-1: esclude gli intent con un settlement on-chain osservato/finale —
    un pagamento arrivato on-chain non va mai negato dal timer di scadenza.
    """
    from app.services.intent_service import settlement_hold_exists

    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(PaymentIntent).where(
            and_(
                PaymentIntent.status == IntentStatus.pending,
                PaymentIntent.expires_at <= now,
                ~settlement_hold_exists(),
            )
        )
    )
    expired = result.scalars().all()

    for intent in expired:
        intent.status = IntentStatus.expired
        await _dispatch_event(
            db,
            merchant_id=intent.merchant_id,
            event_type="payment.expired",
            intent=intent,
        )

    if expired:
        await db.flush()
        logger.info("Expired %d stale payment intents", len(expired))

    return len(expired)


# ═══════════════════════════════════════════════════════════════
#  3. Dispatch Event — crea WebhookDelivery per ogni URL
# ═══════════════════════════════════════════════════════════════

async def _dispatch_event(
    db: AsyncSession,
    *,
    merchant_id: str,
    event_type: str,
    intent: PaymentIntent,
    extra_payload: Optional[dict] = None,
) -> None:
    """Crea una WebhookDelivery per ogni webhook attivo del merchant che ascolta event_type."""

    result = await db.execute(
        select(MerchantWebhook).where(
            and_(
                MerchantWebhook.merchant_id == merchant_id,
                MerchantWebhook.environment == intent.environment,
                MerchantWebhook.is_active == True,
            )
        )
    )
    webhooks = result.scalars().all()

    payload = _build_payload(event_type, intent, extra=extra_payload)

    for wh in webhooks:
        # Filtra per event type
        if wh.events and event_type not in wh.events:
            continue

        # Idempotency key: intent_id + event_type + webhook_id → unico
        idem_key = f"{intent.intent_id}:{event_type}:{wh.id}"

        # Check duplicato
        existing = await db.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.idempotency_key == idem_key,
            )
        )
        if existing.scalar_one_or_none() is not None:
            logger.debug("Duplicate delivery skipped: %s", idem_key)
            continue

        delivery = WebhookDelivery(
            webhook_id=wh.id,
            idempotency_key=idem_key,
            event_type=event_type,
            payload=payload,
            status=DeliveryStatus.pending,
            retries=0,
            next_retry_at=datetime.now(timezone.utc),
        )
        db.add(delivery)

    await db.flush()


def _build_payload(
    event_type: str,
    intent: PaymentIntent,
    extra: Optional[dict] = None,
) -> dict:
    """The ONE webhook body builder — every outbound event (lifecycle,
    settlement, test-fire) goes through here so shapes cannot drift apart.

    This dict is the v1 DATA CONTRACT merchants build against: the exact key
    set is pinned by tests/test_webhook_contract.py, and the published example
    (apps/web/app/docs/webhooks/page.tsx) must move in the same PR as any
    change here. Conventions: `amount` is a STRING; `chain` is the canonical
    lowercase registry name with numeric `chain_id` (no legacy `network`
    alias); no `merchant_id` (identity echo, wallet-address-era); no `fee`
    (subscription model — the on-chain fee stays readable from the PaymentMade
    event via tx_hash). Per-event extras merge last and may override tx_hash.
    """
    now = datetime.now(timezone.utc)
    raw_chain = getattr(intent, "chain", None) or "base"
    chain = _canonical_chain(raw_chain) or raw_chain.lower()
    payload = {
        # event_id: identificatore univoco e stabile dell'evento (persistito sul
        # delivery, invariato tra i retry) → i merchant possono deduplicare e
        # ordinare gli eventi (es. paid prima di reversed) tramite event + timestamp.
        "event_id": "evt_" + uuid.uuid4().hex,
        "event": event_type,
        "intent_id": intent.intent_id,
        "reference_id": getattr(intent, "reference_id", None),
        "onchain_invoice_id": getattr(intent, "onchain_invoice_id", None),
        "amount": str(intent.amount),
        "amount_received": getattr(intent, "amount_received", None),
        "overpaid_amount": getattr(intent, "overpaid_amount", None),
        "underpaid_amount": getattr(intent, "underpaid_amount", None),
        "currency": intent.currency,
        "chain": chain,
        "chain_id": chain_id_for(chain),
        "recipient": intent.recipient,
        "tx_hash": intent.matched_tx_hash or intent.tx_hash,
        "status": intent.status.value,
        "completed_late": intent.completed_late or False,
        "late_minutes": intent.late_minutes,
        "metadata": intent.metadata_,
        "timestamp": now.isoformat(),
        "created_at": intent.created_at.isoformat() if intent.created_at else None,
        "completed_at": intent.completed_at.isoformat() if intent.completed_at else None,
    }
    if extra:
        payload.update(extra)
    return payload


def _finalize_event_type(intent: PaymentIntent) -> str:
    """Event name for a finalized intent. `review` maps to the subscribable
    `payment.needs_review` — the raw f-string produced `payment.review`,
    which no allowlist or subscription filter matched, so merchants
    silently never received it."""
    if intent.completed_late:
        return "payment.completed_late"
    if intent.status == IntentStatus.review:
        return "payment.needs_review"
    return f"payment.{intent.status.value}"


# ═══════════════════════════════════════════════════════════════
#  4. Process Pending Deliveries — chiamato periodicamente
# ═══════════════════════════════════════════════════════════════

async def process_pending_deliveries(db: AsyncSession) -> int:
    """
    Processa tutte le delivery pending il cui next_retry_at è passato.
    Chiamato periodicamente (es. ogni 15s da Celery beat).

    Returns:
        Numero di delivery processate in questo batch.
    """
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(WebhookDelivery).where(
            and_(
                WebhookDelivery.status == DeliveryStatus.pending,
                WebhookDelivery.next_retry_at <= now,
            )
        ).limit(50)  # batch size
    )
    deliveries = result.scalars().all()

    processed = 0
    for delivery in deliveries:
        # Fetch il webhook associato
        wh_result = await db.execute(
            select(MerchantWebhook).where(MerchantWebhook.id == delivery.webhook_id)
        )
        webhook = wh_result.scalar_one_or_none()

        if webhook is None or not webhook.is_active:
            delivery.status = DeliveryStatus.failed
            delivery.response_body = "Webhook not found or inactive"
            continue

        success = await _attempt_delivery(delivery, webhook)
        processed += 1

    await db.flush()
    return processed


def _permanent_reason_for_status(status_code: int) -> Optional[str]:
    """404/410 mean the URL is not there. Every other non-2xx — 5xx especially,
    but also 401/403/422 — is a server that exists and is answering wrongly, so
    it stays transient and the backoff handles it."""
    return PERMANENT_HTTP_REASONS.get(status_code)


def _permanent_reason_for_exception(exc: BaseException) -> Optional[str]:
    """Only a name that does not resolve is permanent.

    THE DISCRIMINATION IS ON `__cause__`, NOT ON THE EXCEPTION TYPE. httpx raises
    `ConnectError` for BOTH a dead DNS name (cause: socket.gaierror) and a host
    that refuses the connection (cause: ConnectionRefusedError). Classifying on
    `isinstance(exc, httpx.ConnectError)` alone would disable every endpoint
    whose server happened to be restarting. Pinned by
    test_webhook_auto_disable.py::test_three_consecutive_connection_refused_do_not_disable.
    """
    if isinstance(exc, httpx.ConnectError) and isinstance(
        exc.__cause__, socket.gaierror
    ):
        return DNS_FAILURE_REASON
    return None


async def _note_delivery_success(webhook: MerchantWebhook) -> None:
    """Any success clears the slate. The counter measures a CONSECUTIVE run, not
    a lifetime total — a working endpoint must never accumulate permanent blame
    from before it recovered.

    Atomic for the same reason the increment is: the reset must not be computed
    from a value read before it. The `!= 0` in the WHERE keeps the common case
    (a healthy endpoint delivering normally) to a no-op UPDATE that matches no
    rows, so there is no per-delivery write amplification.
    """
    db = async_object_session(webhook)
    if db is None:  # defensive: a detached instance has nothing to update
        return

    reset = await db.execute(
        update(MerchantWebhook)
        .where(
            MerchantWebhook.id == webhook.id,
            MerchantWebhook.consecutive_permanent_failures != 0,
        )
        .values(consecutive_permanent_failures=0)
        .execution_options(synchronize_session=False)
    )
    if reset.rowcount:
        await db.refresh(webhook)


async def _note_permanent_failure(webhook: MerchantWebhook, reason: str) -> None:
    """Count ONE permanently-failed delivery and disable at the threshold.

    Called once per delivery that has GIVEN UP, never per attempt — one
    permanent failure is already MAX_RETRIES attempts over hours. Incrementing
    per attempt would disable a dead endpoint on its first delivery instead of
    its third (pinned by
    test_webhook_auto_disable.py::test_one_failed_delivery_counts_once_not_once_per_attempt).

    THE INCREMENT IS A SINGLE ATOMIC UPDATE THAT READS THE NEW VALUE BACK, and
    the disable decision is made from THAT value — never from one read before
    the update. A dead endpoint fails on every event at once, so two workers
    giving up on the same endpoint simultaneously is the normal case here, not
    an edge case: a read-modify-write on the ORM attribute loses one of the two
    increments, disabling then takes more failures than intended, and nobody
    notices because the symptom is that the logs keep filling. Same
    claim-in-the-WHERE shape as `_claim_intent_expiry`; no lock, and the poller
    batch is not serialised. Pinned by
    test_webhook_auto_disable.py::test_two_deliveries_exhausting_concurrently_both_count.
    """
    db = async_object_session(webhook)
    if db is None:  # defensive: a detached instance has nothing to update
        return

    failures = (await db.execute(
        update(MerchantWebhook)
        .where(MerchantWebhook.id == webhook.id)
        .values(
            consecutive_permanent_failures=(
                MerchantWebhook.consecutive_permanent_failures + 1
            )
        )
        .returning(MerchantWebhook.consecutive_permanent_failures)
        .execution_options(synchronize_session=False)
    )).scalar_one()

    if failures >= DISABLE_AFTER_PERMANENT_FAILURES:
        # `is_active == True` in the WHERE makes the disable a CLAIM: if a
        # racing worker crossed the threshold first, rowcount is 0 — we neither
        # overwrite its reason/timestamp with ours nor log a second WARNING for
        # what is one event.
        claim = await db.execute(
            update(MerchantWebhook)
            .where(
                MerchantWebhook.id == webhook.id,
                MerchantWebhook.is_active == True,  # noqa: E712
            )
            .values(
                is_active=False,
                disabled_reason=reason,
                disabled_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )
        if claim.rowcount == 1:
            # WARNING, not ERROR: this is the system working. It names the
            # endpoint AND the merchant because that is what an operator needs
            # to answer "why did this merchant stop getting notified, and since
            # when?".
            logger.warning(
                "Webhook auto-disabled after %d consecutive permanent failures: "
                "webhook_id=%s url=%s merchant=%s reason=%s",
                failures, webhook.id, webhook.url, webhook.merchant_id, reason,
            )

    # The UPDATEs deliberately bypassed the identity map, so this session's copy
    # is stale — including `is_active`, which the poller re-checks on its next
    # delivery for this same endpoint. Reload rather than assigning locally: an
    # assignment would be flushed later and could clobber a concurrent worker's
    # write with our older value.
    await db.refresh(webhook)


async def _attempt_delivery(delivery: WebhookDelivery, webhook: MerchantWebhook) -> bool:
    """
    Tenta una singola consegna HTTP POST al webhook URL.
    Aggiorna delivery.status, response_code, retries, next_retry_at.

    Also maintains the endpoint's auto-disable state on `webhook`: a 2xx resets
    the consecutive-permanent-failure counter, and a delivery that EXHAUSTS its
    retries against a permanently-failed target increments it (see
    `_note_permanent_failure`). `webhook` is a session-attached instance on both
    call paths, so these mutations flush with the caller's transaction.

    Returns:
        True se consegnato con successo (2xx), False altrimenti.
    """
    # Re-validate egress before every attempt (a URL clean at registration
    # could rebind to a private IP later). Fail the delivery permanently — the
    # target is not a legitimate public endpoint.
    reason = await check_webhook_egress(webhook.url)
    if reason is not None:
        delivery.status = DeliveryStatus.failed
        delivery.response_code = None
        delivery.response_body = f"blocked_egress:{reason}"
        logger.error(
            "Webhook delivery blocked (egress): %s → %s reason=%s",
            delivery.idempotency_key, webhook.url, reason,
        )
        # This delivery has ALREADY given up — the branch is terminal and never
        # enters the retry ladder, so it counts here rather than at the
        # MAX_RETRIES exit below. Consequence, and it is intended: three
        # egress-blocked events disable an endpoint in MINUTES where three 404s
        # take ~8 hours. A URL we refuse to contact is a configuration error,
        # not a temporary one.
        await _note_permanent_failure(webhook, f"{EGRESS_REASON_PREFIX}{reason}")
        return False

    payload_bytes = json.dumps(delivery.payload, default=str).encode("utf-8")
    # Timestamp per-attempt (ricalcolato su ogni retry); la firma copre i byte
    # esatti inviati + il timestamp → anti-replay lato merchant.
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    signature = compute_webhook_signature(webhook.secret, timestamp, payload_bytes)

    delivery_uuid = str(uuid.uuid4())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": WEBHOOK_USER_AGENT,
        WEBHOOK_SIGNATURE_HEADER: signature,
        WEBHOOK_TIMESTAMP_HEADER: timestamp,
        "X-RSend-Event": delivery.event_type,
        "X-RSend-Delivery": delivery_uuid,
        "X-RSend-Delivery-Id": delivery.idempotency_key,
    }

    # Why THIS attempt failed permanently, or None if it was transient. Only the
    # attempt that exhausts the ladder is consulted (see below).
    permanent_reason: Optional[str] = None

    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
            resp = await client.post(
                webhook.url,
                content=payload_bytes,
                headers=headers,
            )

        delivery.response_code = resp.status_code
        delivery.response_body = resp.text[:500] if resp.text else None

        if 200 <= resp.status_code < 300:
            delivery.status = DeliveryStatus.delivered
            delivery.delivered_at = datetime.now(timezone.utc)
            await _note_delivery_success(webhook)
            logger.info(
                "Webhook delivered: %s → %s (HTTP %d)",
                delivery.idempotency_key, webhook.url, resp.status_code,
            )
            return True

        # Non-2xx → schedule retry
        permanent_reason = _permanent_reason_for_status(resp.status_code)
        logger.warning(
            "Webhook failed: %s → %s (HTTP %d, retry %d/%d)",
            delivery.idempotency_key, webhook.url,
            resp.status_code, delivery.retries, MAX_RETRIES,
        )

    except httpx.TimeoutException:
        # Transient by definition — a slow endpoint is a working endpoint.
        delivery.response_code = None
        delivery.response_body = "Timeout"
        logger.warning(
            "Webhook timeout: %s → %s (retry %d/%d)",
            delivery.idempotency_key, webhook.url, delivery.retries, MAX_RETRIES,
        )
    except Exception as exc:
        permanent_reason = _permanent_reason_for_exception(exc)
        delivery.response_code = None
        delivery.response_body = str(exc)[:500]
        logger.error(
            "Webhook error: %s → %s (%s, retry %d/%d)",
            delivery.idempotency_key, webhook.url, exc,
            delivery.retries, MAX_RETRIES,
        )

    # ── Retry logic ──────────────────────────────────────
    delivery.retries += 1

    if delivery.retries >= MAX_RETRIES:
        delivery.status = DeliveryStatus.failed
        logger.error(
            "Webhook permanently failed after %d retries: %s → %s",
            MAX_RETRIES, delivery.idempotency_key, webhook.url,
        )
        # ONE increment per delivery that gave up — this is the give-up point,
        # reached once per delivery after MAX_RETRIES attempts. The FINAL
        # attempt decides: 500,500,500,500,404 counts; 404,500,500,500,500 does
        # not, because by the end the server was answering.
        if permanent_reason is not None:
            await _note_permanent_failure(webhook, permanent_reason)
        return False

    # Exponential backoff: 30s * 4^retry
    backoff = BASE_BACKOFF_SECONDS * (4 ** delivery.retries)
    delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)

    logger.info(
        "Webhook retry scheduled: %s → %ds (attempt %d/%d)",
        delivery.idempotency_key, backoff, delivery.retries + 1, MAX_RETRIES,
    )
    return False


# ═══════════════════════════════════════════════════════════════
#  5. Send Test Event — per /api/v1/merchant/webhook/test
# ═══════════════════════════════════════════════════════════════

def _build_test_event_payload(webhook: MerchantWebhook) -> dict:
    """'test' event body — built by the SAME `_build_payload` as every real
    event (via a synthetic, never-persisted intent), so what the "Send test"
    button delivers is exactly the production shape. Chain identity derives
    from the active network — never a hardcoded mainnet literal."""
    from app.services.router_registry import primary_chain_id, chain_name_for_id

    now = datetime.now(timezone.utc)
    intent = PaymentIntent(
        intent_id="pi_test_000000000000",
        merchant_id=webhook.merchant_id,
        amount=10.0,
        currency="USDC",
        chain=chain_name_for_id(primary_chain_id()),
        recipient="0x" + "0" * 40,
        status=IntentStatus.completed,
        metadata_={"test": True},
        created_at=now,
        completed_at=now,
    )
    return _build_payload("test", intent)


async def send_test_event(webhook: MerchantWebhook) -> tuple:
    """
    Invia un evento test al webhook URL.

    Returns:
        (success, status_code, message)
    """
    test_payload = _build_test_event_payload(webhook)

    # Re-validate egress immediately before the POST (DNS-rebinding window).
    reason = await check_webhook_egress(webhook.url)
    if reason is not None:
        logger.warning(
            "Webhook test blocked (egress): id=%s url=%s reason=%s",
            webhook.id, webhook.url, reason,
        )
        return False, None, f"Blocked: URL is not an allowed target ({reason})"

    payload_bytes = json.dumps(test_payload, default=str).encode("utf-8")
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    signature = compute_webhook_signature(webhook.secret, timestamp, payload_bytes)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": WEBHOOK_USER_AGENT,
        WEBHOOK_SIGNATURE_HEADER: signature,
        WEBHOOK_TIMESTAMP_HEADER: timestamp,
        "X-RSend-Event": "test",
        "X-RSend-Delivery-Id": f"test:{webhook.id}:{datetime.now(timezone.utc).isoformat()}",
    }

    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
            resp = await client.post(
                webhook.url,
                content=payload_bytes,
                headers=headers,
            )

        if 200 <= resp.status_code < 300:
            return True, resp.status_code, "Test event delivered successfully"
        return False, resp.status_code, f"Endpoint returned HTTP {resp.status_code}"

    except httpx.TimeoutException:
        return False, None, "Timeout: endpoint did not respond within 10s"
    except Exception as exc:
        return False, None, f"Connection error: {exc}"


# ═══════════════════════════════════════════════════════════════
#  6. send_webhook() — Public API per transaction_matcher & altri
# ═══════════════════════════════════════════════════════════════
# NOTE (idempotency): NO out-of-band pre-claim here. Delivery idempotency
# lives entirely in the DB transaction that owns the WebhookDelivery row
# (dedup SELECT + UNIQUE idempotency_key), so it commits or rolls back WITH
# the row. The removed Redis SETNX pre-claim survived rollbacks its row did
# not — orphan claim, 7 days of silently suppressed retries — and was
# fail-open on Redis loss, so it guaranteed nothing. Cross-process
# exactly-once is owned by the callers' atomic claims (webhook_fired_at /
# reversal_fired_at / the expire task's pending→expired UPDATE-WHERE).

async def send_webhook(
    db: AsyncSession,
    *,
    merchant_id: str,
    event: str,
    intent: PaymentIntent,
    extra_payload: Optional[dict] = None,
) -> int:
    """
    Public API — invia un webhook a tutti gli endpoint attivi del merchant.

    Chiamato da transaction_matcher.py, expire task, e qualsiasi servizio
    che deve notificare il merchant.

    Workflow:
      1. Trova tutti i webhook attivi del merchant che ascoltano `event`
      2. Per ciascuno, controlla idempotenza DB (WebhookDelivery, stessa tx)
      3. Crea WebhookDelivery con status=pending
      4. Tenta delivery immediata; se fallisce, schedula retry

    Args:
        db: Sessione DB asincrona
        merchant_id: ID del merchant
        event: Tipo evento ("payment.completed", "payment.expired", "payment.failed")
        intent: PaymentIntent associato
        extra_payload: Campi extra da aggiungere al payload

    Returns:
        Numero di delivery create (0 se nessun webhook attivo o tutti duplicati).
    """
    result = await db.execute(
        select(MerchantWebhook).where(
            and_(
                MerchantWebhook.merchant_id == merchant_id,
                MerchantWebhook.environment == intent.environment,
                MerchantWebhook.is_active == True,
            )
        )
    )
    webhooks = result.scalars().all()

    if not webhooks:
        logger.debug(
            "No active webhooks for merchant %s, event %s", merchant_id, event,
        )
        return 0

    payload = _build_payload(event, intent, extra=extra_payload)
    created = 0

    for wh in webhooks:
        # Filtra per event type
        if wh.events and event not in wh.events:
            continue

        idem_key = f"{intent.intent_id}:{event}:{wh.id}"

        # ── DB idempotency (durable, dies with this transaction) ──
        existing = await db.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.idempotency_key == idem_key,
            )
        )
        if existing.scalar_one_or_none() is not None:
            logger.debug("DB idempotency hit: %s — skipping", idem_key)
            continue

        # ── Crea delivery record ──
        delivery_id = str(uuid.uuid4())
        delivery = WebhookDelivery(
            webhook_id=wh.id,
            idempotency_key=idem_key,
            event_type=event,
            payload=payload,
            status=DeliveryStatus.pending,
            retries=0,
            next_retry_at=datetime.now(timezone.utc),
        )
        db.add(delivery)
        await db.flush()
        created += 1

        # ── Tentativo immediato di delivery ──
        success = await _attempt_delivery(delivery, wh)
        if success:
            logger.info(
                "send_webhook: immediate delivery OK for %s → %s",
                idem_key, wh.url,
            )
        else:
            logger.info(
                "send_webhook: immediate delivery failed for %s, retry scheduled",
                idem_key,
            )

    await db.flush()
    return created


# (the second builder that lived here — `_build_merchant_payload` — was folded
# into `_build_payload` above: two independent builders were the root cause of
# the payload-shape drift between lifecycle and settlement webhooks)
