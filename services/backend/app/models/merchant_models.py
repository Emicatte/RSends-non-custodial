"""
RSend Backend — Merchant B2B Models.

Modelli SQLAlchemy + Pydantic schemas per il layer B2B:
  - PaymentIntent: richiesta di pagamento creata dal merchant
  - MerchantWebhook: URL registrati per ricevere notifiche
  - WebhookDelivery: log di ogni tentativo di consegna webhook
"""

from datetime import datetime, timezone, timedelta
from sqlalchemy import (
    Column, String, Float, Boolean, DateTime, Integer,
    Text, ForeignKey, Index, Enum as SAEnum, JSON,
    CheckConstraint, UniqueConstraint, text,
)
from sqlalchemy.orm import relationship
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional
import enum
import hashlib
import secrets

from app.models.db_models import Base


# ═══════════════════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════════════════

class IntentStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"               # NON-CUSTODIAL: on-chain PaymentMade observed → settled to merchant
    completed = "completed"     # legacy alias (kept for backward compatibility)
    expired = "expired"
    cancelled = "cancelled"
    review = "review"
    refunded = "refunded"
    partial = "partial"
    overpaid = "overpaid"


class LatePaymentPolicy(str, enum.Enum):
    REJECT = "reject"         # Rifiuta: non matchare, fondi restano al sender
    AUTO_COMPLETE = "auto"    # Accetta con flag: completa l'intent con flag "late"
    REVIEW = "review"         # Manual review: crea ticket, non completare automaticamente


class DeliveryStatus(str, enum.Enum):
    pending = "pending"
    delivered = "delivered"
    failed = "failed"


# ═══════════════════════════════════════════════════════════════
#  Reference ID Generator — fingerprint merchant + random
# ═══════════════════════════════════════════════════════════════

def generate_reference_id(merchant_id: str) -> str:
    """
    Genera reference_id che include un fingerprint del merchant.

    Non è reversibile ma permette validazione interna.
    Format: 4 char fingerprint (SHA-256 del merchant_id) + 12 char random = 16 char totali.
    """
    random_part = secrets.token_hex(6)  # 12 hex chars
    fingerprint = hashlib.sha256(merchant_id.encode()).hexdigest()[:4]
    return f"{fingerprint}{random_part}"


# ═══════════════════════════════════════════════════════════════
#  PaymentIntent — richiesta di pagamento dal merchant
# ═══════════════════════════════════════════════════════════════

class PaymentIntent(Base):
    __tablename__ = "payment_intents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    intent_id = Column(String(64), unique=True, nullable=False, index=True)

    # Disambiguation — reference_id incluso nel calldata/memo della TX
    reference_id = Column(
        String(16),
        unique=True,
        nullable=False,
        default=lambda: secrets.token_hex(8),   # 16 hex chars, es: "a3f8b2c1e9d04f7a"
        index=True,
    )

    # Merchant
    merchant_id = Column(String(64), nullable=False, index=True)

    # Environment binding: "test" | "live". Derived from the API key at create
    # time. merchant_id is the owner address — IDENTICAL across an owner's test
    # and live keys — so this column is what isolates test data from live data
    # on every read/mutate. Defaults to "live" so legacy rows stay live-only.
    environment = Column(
        String(8), nullable=False, default="live", server_default="live",
    )

    # Pagamento
    amount = Column(Float, nullable=False)
    currency = Column(String(16), nullable=False)           # "USDC", "ETH", ecc.
    recipient = Column(String(42), nullable=True)           # Indirizzo di ricezione
    network = Column(String(32), nullable=True)             # "BASE_MAINNET", ecc.
    expected_sender = Column(String(42), nullable=True)     # Wallet pagante atteso (opzionale)

    # Stato
    status = Column(
        SAEnum(IntentStatus), nullable=False, default=IntentStatus.pending,
    )

    # Riconciliazione
    tx_hash = Column(String(66), nullable=True, index=True)
    metadata_ = Column("metadata", JSON, nullable=True)     # dati merchant arbitrari

    # NON-CUSTODIAL: on-chain invoiceId (bytes32 hex) the payer passes to
    # RSendsRouter.pay(); the indexer matches the emitted PaymentMade.invoiceId
    # back to this intent. Replaces the custodial deposit_address.
    onchain_invoice_id = Column(String(66), nullable=True, index=True)

    # Chain su cui accettare il pagamento (default BASE)
    chain = Column(String(32), nullable=False, default="BASE")

    # Matching — hash della TX on-chain che ha matchato + timestamp
    matched_tx_hash = Column(String(66), nullable=True, index=True)
    matched_at = Column(DateTime(timezone=True), nullable=True)

    # Scadenza
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Late payment policy + tracking
    late_payment_policy = Column(
        String(10),
        default=LatePaymentPolicy.AUTO_COMPLETE.value,
        nullable=False,
    )
    completed_late = Column(Boolean, default=False, nullable=False)
    late_minutes = Column(Integer, nullable=True)

    # Amount tracking (Bug 4: under/overpayment)
    amount_received = Column(String, default="0")
    overpaid_amount = Column(String, nullable=True)
    underpaid_amount = Column(String, nullable=True)

    # Merchant tolerance config (Bug 4)
    amount_tolerance_percent = Column(Float, default=1.0)
    allow_partial = Column(Boolean, default=False)
    allow_overpayment = Column(Boolean, default=True)

    # NON-CUSTODIAL: platform-fee sweep tracking removed. Any protocol fee is
    # taken atomically on-chain by RSendsRouter (if enabled); RSends never
    # sweeps funds. Billing is derived from settled on-chain payments instead.

    # NON-CUSTODIAL SPLIT: quando l'intent è una split, `recipient` resta NULL
    # (nessun payee singolo) e i destinatari vivono in payment_intent_recipients
    # (ordine = position, share in bps ESATTI a somma 10000). Eager load
    # (selectin) così serializer e indexer li hanno sempre senza lazy-IO async.
    split_recipients = relationship(
        "PaymentIntentRecipient",
        order_by="PaymentIntentRecipient.position",
        lazy="selectin",
        viewonly=True,
    )

    __table_args__ = (
        Index("ix_intent_merchant_status", "merchant_id", "status"),
        Index("ix_intent_status_expires", "status", "expires_at"),
        # One pending intent per payable coordinate — migration 0019.
        # A watch-only transfer carries no invoiceId and can only be matched on
        # (recipient, token, amount, window), so a duplicate pending tuple makes
        # an arriving payment genuinely ambiguous. Declared here as well as in
        # the migration because the test suite builds schema with create_all,
        # never with alembic; 0019 is existence-guarded for the same reason.
        # `environment` and `chain` are IN the key: ambiguity only exists
        # between intents one transfer could BOTH be, and a test intent is
        # never a candidate for a live transfer (every path is already filtered
        # by environment) nor a Base intent for a TRON one.
        # On the float column deliberately — see 0019's docstring: the ingest
        # scale gate bounds `amount`, so distinct accepted amounts differ by at
        # least one base unit and this separates exactly what the matcher
        # compares. An expression index reproducing to_base_units is not
        # writable in SQL.
        Index(
            "uq_intent_pending_amount",
            "merchant_id", "environment", "chain", "currency", "amount",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )


# ═══════════════════════════════════════════════════════════════
#  PaymentIntentRecipient — destinatari di una split (bps, somma == 10000)
# ═══════════════════════════════════════════════════════════════

class PaymentIntentRecipient(Base):
    """One leg of a split intent. position 0 = primary (receives the integer
    remainder on-chain). The BPS-exact invariant (sum == 10000) is enforced at
    the schema gate AND by the contract; the DB check bounds each single leg."""
    __tablename__ = "payment_intent_recipients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    intent_id = Column(
        String(64),
        ForeignKey("payment_intents.intent_id"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False)
    address = Column(String(42), nullable=False)     # lowercase, regex-gated
    share_bps = Column(Integer, nullable=False)
    label = Column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("intent_id", "position", name="uq_intent_recipient_position"),
        UniqueConstraint("intent_id", "address", name="uq_intent_recipient_address"),
        CheckConstraint(
            "share_bps >= 1 AND share_bps <= 10000", name="ck_intent_recipient_bps"
        ),
    )


# ═══════════════════════════════════════════════════════════════
#  MerchantWebhook — URL registrati per notifiche
# ═══════════════════════════════════════════════════════════════

class MerchantWebhook(Base):
    __tablename__ = "merchant_webhooks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(64), nullable=False, index=True)

    # Environment binding: "test" | "live". Stamped from the API key at
    # register time. merchant_id is the owner address — IDENTICAL across an
    # owner's test and live keys — so this column is what keeps test webhooks
    # from receiving live events (and vice versa) on lookup AND dispatch.
    environment = Column(
        String(8), nullable=False, default="live", server_default="live",
    )

    url = Column(String(2048), nullable=False)
    secret = Column(String(128), nullable=False)            # HMAC secret per verifica
    events = Column(JSON, nullable=False, default=list)     # ["payment.completed", "payment.expired"]
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    deliveries = relationship("WebhookDelivery", back_populates="webhook")


# ═══════════════════════════════════════════════════════════════
#  WebhookDelivery — log di ogni tentativo di consegna
# ═══════════════════════════════════════════════════════════════

class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    webhook_id = Column(
        Integer, ForeignKey("merchant_webhooks.id"), nullable=False,
    )
    idempotency_key = Column(String(128), unique=True, nullable=False)

    # Evento
    event_type = Column(String(64), nullable=False)         # "payment.completed"
    payload = Column(JSON, nullable=False)

    # Delivery status
    status = Column(
        SAEnum(DeliveryStatus), nullable=False, default=DeliveryStatus.pending,
    )
    response_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    retries = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    delivered_at = Column(DateTime(timezone=True), nullable=True)

    webhook = relationship("MerchantWebhook", back_populates="deliveries")

    __table_args__ = (
        Index("ix_delivery_status_retry", "status", "next_retry_at"),
    )


# ═══════════════════════════════════════════════════════════════
#  Pydantic Schemas — Request / Response
# ═══════════════════════════════════════════════════════════════

# ── Payment Intent ────────────────────────────────────────────

class SplitRecipientInput(BaseModel):
    """One split leg in a create request: EVM address + integer basis points."""
    address: str = Field(..., max_length=42, description="Indirizzo destinatario del leg")
    share_bps: int = Field(..., ge=1, le=10000, description="Quota in basis points (1..10000)")
    label: Optional[str] = Field(None, max_length=64, description="Etichetta display opzionale")

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        import re
        if not re.match(r"^0x[a-fA-F0-9]{40}$", v):
            raise ValueError("split address deve essere un indirizzo Ethereum valido")
        return v.lower()


class SplitRecipientOut(BaseModel):
    """One split leg as serialized in responses (merchant list + public view)."""
    address: str
    share_bps: int
    position: int
    label: Optional[str] = None


class CreatePaymentIntentRequest(BaseModel):
    """POST /api/v1/merchant/payment-intent"""
    amount: float = Field(..., gt=0, description="Importo richiesto")
    currency: str = Field(..., max_length=16, description="Token: USDC, ETH, ecc.")
    recipient: Optional[str] = Field(None, max_length=42, description="Indirizzo destinatario")
    network: Optional[str] = Field(None, description="Rete: BASE_MAINNET, ecc.")
    expected_sender: Optional[str] = Field(None, max_length=42, description="Indirizzo wallet del pagante atteso (opzionale)")
    metadata: Optional[dict] = Field(None, description="Dati arbitrari del merchant (order_id, customer, ecc.)")
    chain: str = Field("BASE", max_length=32, description="Chain su cui accettare il pagamento: BASE, ETH, ARBITRUM, ecc.")
    expires_in_minutes: int = Field(30, ge=5, le=1440, description="Scadenza in minuti (default 30, max 24h)")
    late_payment_policy: str = Field("auto", description="Policy per pagamento in ritardo: 'reject', 'auto', 'review'")
    amount_tolerance_percent: float = Field(1.0, ge=0.0, le=10.0, description="Tolleranza percentuale sull'importo (default 1%)")
    allow_partial: bool = Field(False, description="Accetta pagamenti parziali (>=50% dell'importo)?")
    allow_overpayment: bool = Field(True, description="Accetta pagamenti in eccesso?")
    split: Optional[list[SplitRecipientInput]] = Field(
        None,
        description=(
            "Split non-custodial: 2..20 destinatari con quote in basis points "
            "a somma ESATTA 10000. Mutuamente esclusivo con `recipient`."
        ),
    )

    @field_validator("split")
    @classmethod
    def validate_split(cls, v: Optional[list[SplitRecipientInput]]) -> Optional[list[SplitRecipientInput]]:
        if v is None:
            return v
        # Validate & REJECT, never coerce — the BPS-exact invariant lives here
        # (schema gate) AND in the contract (revert). No "close enough".
        if not (2 <= len(v) <= 20):
            raise ValueError("split richiede da 2 a 20 destinatari")
        addresses = [r.address for r in v]
        if len(set(addresses)) != len(addresses):
            raise ValueError("split: indirizzi duplicati non ammessi")
        total_bps = sum(r.share_bps for r in v)
        if total_bps != 10000:
            raise ValueError(
                f"split: le quote devono sommare esattamente a 10000 bps (ricevuto {total_bps})"
            )
        return v

    @model_validator(mode="after")
    def validate_split_recipient_exclusive(self):
        if self.split is not None and self.recipient is not None:
            raise ValueError(
                "recipient e split sono mutuamente esclusivi: o un payee singolo o una split"
            )
        return self

    @field_validator("late_payment_policy")
    @classmethod
    def validate_late_payment_policy(cls, v: str) -> str:
        allowed = {"reject", "auto", "review"}
        if v not in allowed:
            raise ValueError(f"late_payment_policy deve essere uno di: {sorted(allowed)}")
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        allowed = {"ETH", "USDC", "USDT", "DAI", "cbBTC", "DEGEN"}
        if v not in allowed:
            raise ValueError(f"currency deve essere uno di: {allowed}")
        return v

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, v: Optional[str]) -> Optional[str]:
        # EVM addresses fold to lowercase exactly as before. TRON addresses are
        # base58check and case-SENSITIVE — lowercasing one destroys it (base58
        # has no 0 O I l), so they are validated by checksum and stored verbatim.
        if v is not None:
            from app.security.input_validator import normalize_payment_address

            normalized = normalize_payment_address(v)
            if normalized is None:
                raise ValueError(
                    "recipient deve essere un indirizzo Ethereum (0x…) o TRON (T…) valido"
                )
            return normalized
        return v

    @field_validator("expected_sender")
    @classmethod
    def validate_expected_sender(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            from app.security.input_validator import normalize_payment_address

            normalized = normalize_payment_address(v)
            if normalized is None:
                raise ValueError(
                    "expected_sender deve essere un indirizzo Ethereum (0x…) o TRON (T…) valido"
                )
            return normalized
        return v


class OnchainSplit(BaseModel):
    """Split fan-out payload for RSendsSplitRouter.paySplit* (camelCase keys).

    `amounts` are the server-computed per-leg base units (floor division,
    remainder to index 0 — bit-identical to the contract math): the checkout
    renders them and passes ONLY total+sharesBps on-chain, so the contract
    recomputes and guarantees the same numbers.
    """
    router: str              # RSendsSplitRouter contract address (fee-less, ownerless)
    recipients: list[str]
    sharesBps: list[int]
    amounts: list[str]       # per-leg base units, index-aligned with recipients


class OnchainPayment(BaseModel):
    """Non-custodial on-chain payment instructions for the payer's wallet.

    camelCase keys match the frontend Pay flow (apps/web/app/pay/[intentId]).
    """
    invoiceId: str
    merchant: str            # single payee; "" when `split` is set (no single payee)
    token: str               # 0x0000...0000 == native ETH
    amount: str              # base units (wei / token decimals)
    fee: Optional[str] = None       # fee in base units, live from quoteFee (None if unavailable)
    total: Optional[str] = None     # amount + fee (what the payer parts with overall)
    maxFee: Optional[str] = None    # payer ceiling passed to pay/payWithPermit/payNative (== fee)
    chainId: int
    router: str              # router contract address (family per routerVersion)
    # Which RSends router family `router`/`calldata` target (meaningful when
    # `split` is None): 1 = RSendsRouter (testnet, on-chain flat fee, maxFee
    # args), 2 = RSendsRouterV2 (fee-less/ownerless mainnet router — fee is
    # literally "0", maxFee None, calldata carries no fee word). The frontend
    # forks its ABI/args on this.
    routerVersion: int = 1
    calldata: Optional[str] = None  # ready-to-send pay()/payNative() calldata (None if fee unavailable)
    payWithPermitCalldata: Optional[str] = None  # template; permit (deadline,v,r,s) filled client-side
    function: str            # "pay" (ERC20, needs approve first) | "payNative"
    decimals: int
    isNative: bool
    # STATIC permit policy from the registry (no runtime introspection):
    #   "eip2612" → payWithPermit flow (permitVersion = EIP-712 domain version)
    #   "none"    → approve()+pay() flow
    permitType: Optional[str] = None
    permitVersion: Optional[str] = None
    feeUnavailable: bool = False    # True if live quoteFee failed → frontend quotes on-chain itself
    # Split fan-out (RSendsSplitRouter). When set: function is paySplit*/
    # paySplitNative, `router` is the split router, fee is "0" (fee-less by
    # design — subscription monetization), and `merchant` is "".
    split: Optional[OnchainSplit] = None


class PaymentIntentResponse(BaseModel):
    intent_id: str
    reference_id: str
    # NON-CUSTODIAL: deposit_address replaced by onchain_invoice_id + `onchain`.
    onchain_invoice_id: Optional[str] = None
    onchain: Optional[OnchainPayment] = None
    amount: float
    currency: str
    chain: str = "BASE"
    recipient: Optional[str]
    split: Optional[list[SplitRecipientOut]] = None  # N-way split legs (recipient is NULL)
    network: Optional[str]
    expected_sender: Optional[str]
    status: str
    metadata: Optional[dict]
    tx_hash: Optional[str]
    matched_tx_hash: Optional[str] = None
    matched_at: Optional[str] = None
    match_confidence: Optional[int] = None   # Score 0-100 se matched via scoring
    completed_late: Optional[bool] = None
    late_minutes: Optional[int] = None
    late_payment_policy: Optional[str] = None
    amount_received: Optional[str] = None
    overpaid_amount: Optional[str] = None
    underpaid_amount: Optional[str] = None
    expires_at: str
    created_at: str
    completed_at: Optional[str]


# ── Webhook Registration ─────────────────────────────────────

VALID_EVENTS = frozenset({
    "payment.completed",
    "payment.completed_late",
    "payment.expired",
    "payment.expired_rejected",
    "payment.needs_review",
    "payment.cancelled",     # reserved: allowlisted, not yet emitted
    "payment.partial",
    "payment.overpaid",
    "payment.ambiguous",     # reserved: allowlisted, not yet emitted
    "payment.reversed",      # reorg reversal (indexer) — subscribable
})


class RegisterWebhookRequest(BaseModel):
    """POST /api/v1/merchant/webhook/register"""
    url: str = Field(..., min_length=10, max_length=2048, description="URL HTTPS del webhook")
    events: list[str] = Field(
        default=["payment.completed"],
        description="Event types da ricevere",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("L'URL del webhook deve usare HTTPS")
        return v

    @field_validator("events")
    @classmethod
    def validate_events(cls, v: list[str]) -> list[str]:
        for e in v:
            if e not in VALID_EVENTS:
                raise ValueError(f"Evento '{e}' non valido. Validi: {sorted(VALID_EVENTS)}")
        return v


class RegisterWebhookResponse(BaseModel):
    webhook_id: int
    url: str
    secret: str = Field(..., description="HMAC secret — mostrare UNA sola volta")
    events: list[str]
    is_active: bool


# ── Webhook Test ──────────────────────────────────────────────

class TestWebhookRequest(BaseModel):
    """POST /api/v1/merchant/webhook/test"""
    webhook_id: int = Field(..., description="ID del webhook da testare")


class TestWebhookResponse(BaseModel):
    status: str
    response_code: Optional[int]
    message: str


# ── Webhook Reads (Phase E) ───────────────────────────────────

class WebhookItem(BaseModel):
    """A registered webhook endpoint. NEVER carries `secret` — the HMAC secret
    is a register-time one-shot (RegisterWebhookResponse) and is never re-read."""
    webhook_id: int
    url: str
    events: list[str]
    is_active: bool
    created_at: str


class WebhookListResponse(BaseModel):
    total: int
    records: list[WebhookItem]


class WebhookDeliveryItem(BaseModel):
    """One delivery attempt row. Deliberately EXCLUDES `payload` and
    `response_body` (OQ-E2): the payload can carry customer PII and the
    response body is arbitrary merchant-server output — neither belongs in a
    session-authed browser view."""
    id: int
    event_type: str
    status: str
    response_code: Optional[int] = None
    retries: int
    next_retry_at: Optional[str] = None
    created_at: str
    delivered_at: Optional[str] = None


class WebhookDeliveryListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    records: list[WebhookDeliveryItem]


# ── Resolve Late Payment ─────────────────────────────────────

class ResolvePaymentRequest(BaseModel):
    """POST /api/v1/merchant/payment-intent/{intent_id}/resolve"""
    action: str = Field(..., description="Azione: 'complete' o 'refund'")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in ("complete", "refund"):
            raise ValueError("action deve essere 'complete' o 'refund'")
        return v


# ── Transaction List ──────────────────────────────────────────

class MerchantTransactionItem(BaseModel):
    intent_id: str
    onchain_invoice_id: Optional[str] = None
    amount: float
    currency: str
    chain: str = "BASE"
    status: str
    recipient: Optional[str] = None  # Phase C: on-chain payee (settlement wallet or override)
    split: Optional[list[SplitRecipientOut]] = None  # N-way split legs (recipient is None)
    tx_hash: Optional[str]
    matched_tx_hash: Optional[str] = None
    metadata: Optional[dict]
    completed_late: Optional[bool] = None
    late_minutes: Optional[int] = None
    amount_received: Optional[str] = None
    overpaid_amount: Optional[str] = None
    underpaid_amount: Optional[str] = None
    created_at: str
    expires_at: Optional[str] = None  # Phase C: ISO-8601; drives the pending-expiry display
    completed_at: Optional[str]


class MerchantTransactionListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    records: list[MerchantTransactionItem]
