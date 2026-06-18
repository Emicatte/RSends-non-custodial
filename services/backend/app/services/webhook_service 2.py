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

import hashlib
import hmac
import json
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant_models import (
    PaymentIntent, IntentStatus, LatePaymentPolicy,
    MerchantWebhook,
    WebhookDelivery, DeliveryStatus,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 30       # 30s * 4^retry → 30s, 2m, 8m, 32m, 2h
DELIVERY_TIMEOUT = 10.0         # httpx timeout per singolo attempt
WEBHOOK_USER_AGENT = "RSend-Webhook/1.0"
REDIS_IDEM_TTL = 7 * 86400              # 7 giorni TTL per chiave idempotenza Redis
REDIS_IDEM_PREFIX = "wh:delivery:idem:"  # Prefisso Redis per idempotenza delivery

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
#  HMAC Signing — il merchant verifica con il suo secret
# ═══════════════════════════════════════════════════════════════

def compute_webhook_signature(secret: str, payload_bytes: bytes) -> str:
    """Compute HMAC-SHA256(secret, raw_body) → hex string."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


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
    event_type = "payment.completed_late" if intent.completed_late else "payment.completed"
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
    event_type = f"payment.{intent.status.value}"
    if intent.completed_late:
        event_type = "payment.completed_late"

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
    """Segna come expired tutti gli intent pending scaduti. Ritorna il count."""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(PaymentIntent).where(
            and_(
                PaymentIntent.status == IntentStatus.pending,
                PaymentIntent.expires_at <= now,
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
                MerchantWebhook.is_active == True,
            )
        )
    )
    webhooks = result.scalars().all()

    payload = _build_event_payload(event_type, intent, extra=extra_payload)

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


def _build_event_payload(
    event_type: str,
    intent: PaymentIntent,
    extra: Optional[dict] = None,
) -> dict:
    """Costruisce il payload JSON dell'evento webhook."""
    now = datetime.now(timezone.utc)
    payload = {
        "event": event_type,
        "intent_id": intent.intent_id,
        "merchant_id": intent.merchant_id,
        "amount": intent.amount,
        "currency": intent.currency,
        "chain": getattr(intent, "chain", "BASE") or "BASE",
        "deposit_address": getattr(intent, "deposit_address", None),
        "recipient": intent.recipient,
        "network": intent.network,
        "tx_hash": intent.matched_tx_hash or intent.tx_hash,
        "status": intent.status.value,
        "metadata": intent.metadata_,
        "timestamp": now.isoformat(),
        "completed_late": intent.completed_late or False,
        "late_minutes": intent.late_minutes,
        "amount_received": getattr(intent, "amount_received", None),
        "overpaid_amount": getattr(intent, "overpaid_amount", None),
        "underpaid_amount": getattr(intent, "underpaid_amount", None),
        "created_at": intent.created_at.isoformat() if intent.created_at else None,
        "completed_at": intent.completed_at.isoformat() if intent.completed_at else None,
    }
    if extra:
        payload.update(extra)
    return payload


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


async def _attempt_delivery(delivery: WebhookDelivery, webhook: MerchantWebhook) -> bool:
    """
    Tenta una singola consegna HTTP POST al webhook URL.
    Aggiorna delivery.status, response_code, retries, next_retry_at.

    Returns:
        True se consegnato con successo (2xx), False altrimenti.
    """
    payload_bytes = json.dumps(delivery.payload, default=str).encode("utf-8")
    signature = compute_webhook_signature(webhook.secret, payload_bytes)

    delivery_uuid = str(uuid.uuid4())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": WEBHOOK_USER_AGENT,
        "X-RSend-Signature": signature,
        "X-RSend-Event": delivery.event_type,
        "X-RSend-Delivery": delivery_uuid,
        "X-RSend-Delivery-Id": delivery.idempotency_key,
    }

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
            logger.info(
                "Webhook delivered: %s → %s (HTTP %d)",
                delivery.idempotency_key, webhook.url, resp.status_code,
            )
            return True

        # Non-2xx → schedule retry
        logger.warning(
            "Webhook failed: %s → %s (HTTP %d, retry %d/%d)",
            delivery.idempotency_key, webhook.url,
            resp.status_code, delivery.retries, MAX_RETRIES,
        )

    except httpx.TimeoutException:
        delivery.response_code = None
        delivery.response_body = "Timeout"
        logger.warning(
            "Webhook timeout: %s → %s (retry %d/%d)",
            delivery.idempotency_key, webhook.url, delivery.retries, MAX_RETRIES,
        )
    except Exception as exc:
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

async def send_test_event(webhook: MerchantWebhook) -> tuple:
    """
    Invia un evento test al webhook URL.

    Returns:
        (success, status_code, message)
    """
    test_payload = {
        "event": "test",
        "intent_id": "pi_test_000000000000",
        "merchant_id": webhook.merchant_id,
        "amount": 10.0,
        "currency": "USDC",
        "recipient": "0x" + "0" * 40,
        "network": "BASE_MAINNET",
        "tx_hash": None,
        "status": "completed",
        "metadata": {"test": True},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    payload_bytes = json.dumps(test_payload, default=str).encode("utf-8")
    signature = compute_webhook_signature(webhook.secret, payload_bytes)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": WEBHOOK_USER_AGENT,
        "X-RSend-Signature": signature,
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
#  6. Redis Idempotency — TTL-based dedup prima del DB check
# ═══════════════════════════════════════════════════════════════

async def _check_redis_idempotency(idem_key: str) -> bool:
    """
    Check se un delivery è già stato schedulato via Redis SETNX.

    Returns:
        True  → chiave già presente, è un duplicato → skip
        False → chiave nuova, procedi con delivery

    Se Redis è down, logga warning e ritorna False (fail-open per webhook
    outbound — diverso dal fail-closed per webhook inbound Alchemy).
    """
    try:
        from app.services.cache_service import get_redis
        r = await get_redis()
        if r is None:
            logger.warning(
                "Redis unavailable for webhook idempotency check — proceeding anyway"
            )
            return False

        redis_key = f"{REDIS_IDEM_PREFIX}{idem_key}"
        was_set = await r.set(redis_key, "1", nx=True, ex=REDIS_IDEM_TTL)
        if not was_set:
            logger.debug("Redis idempotency hit: %s — skipping", idem_key)
            return True
        return False

    except Exception as exc:
        logger.warning(
            "Redis idempotency check failed (%s) — proceeding anyway: %s",
            idem_key, exc,
        )
        return False


# ═══════════════════════════════════════════════════════════════
#  7. send_webhook() — Public API per transaction_matcher & altri
# ═══════════════════════════════════════════════════════════════

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
      2. Per ciascuno, controlla idempotenza Redis (TTL 7gg)
      3. Se nuovo, controlla idempotenza DB (WebhookDelivery)
      4. Crea WebhookDelivery con status=pending
      5. Tenta delivery immediata; se fallisce, schedula retry

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

    payload = _build_merchant_payload(event, intent, extra=extra_payload)
    created = 0

    for wh in webhooks:
        # Filtra per event type
        if wh.events and event not in wh.events:
            continue

        idem_key = f"{intent.intent_id}:{event}:{wh.id}"

        # ── Redis idempotency (fast, TTL-based) ──
        if await _check_redis_idempotency(idem_key):
            continue

        # ── DB idempotency (durable) ──
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


def _build_merchant_payload(
    event_type: str,
    intent: PaymentIntent,
    extra: Optional[dict] = None,
) -> dict:
    """
    Costruisce il payload webhook per merchant con formato completo.

    Include: event, intent_id, amount, currency, chain, tx_hash,
    deposit_address, metadata, timestamp.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "event": event_type,
        "intent_id": intent.intent_id,
        "amount": str(intent.amount),
        "currency": intent.currency,
        "chain": getattr(intent, "chain", "BASE") or "BASE",
        "tx_hash": intent.matched_tx_hash or intent.tx_hash,
        "deposit_address": getattr(intent, "deposit_address", None),
        "metadata": intent.metadata_,
        "timestamp": now.isoformat(),
        # ── Campi estesi per reconciliazione merchant ──
        "status": intent.status.value,
        "reference_id": intent.reference_id,
        "amount_received": getattr(intent, "amount_received", None),
        "overpaid_amount": getattr(intent, "overpaid_amount", None),
        "underpaid_amount": getattr(intent, "underpaid_amount", None),
        "completed_late": intent.completed_late or False,
        "late_minutes": intent.late_minutes,
        "created_at": intent.created_at.isoformat() if intent.created_at else None,
        "completed_at": intent.completed_at.isoformat() if intent.completed_at else None,
    }
    if extra:
        payload.update(extra)
    return payload
