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
)
from sqlalchemy.orm import relationship
from pydantic import BaseModel, Field, field_validator
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
    completed = "completed"
    sweeping = "sweeping"       # Fondi in fase di sweep dal deposit al treasury
    settled = "settled"         # Fondi arrivati al merchant/treasury
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

    # Deposit address — indirizzo unico generato per ogni intent
    deposit_address = Column(String(42), unique=True, nullable=True, index=True)

    # Chain su cui accettare il pagamento (default BASE)
    chain = Column(String(32), nullable=False, default="BASE")

    # Matching — hash della TX che ha matchato + timestamp
    matched_tx_hash = Column(String(66), nullable=True, index=True)
    matched_at = Column(DateTime(timezone=True), nullable=True)

    # Scadenza
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # Sweep — forward fondi dal deposit al treasury/merchant
    sweep_tx_hash = Column(String(66), nullable=True, index=True)
    swept_at = Column(DateTime(timezone=True), nullable=True)

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

    # Platform fee tracking
    fee_bps = Column(Integer, nullable=True)
    fee_amount = Column(String(32), nullable=True)
    fee_tx_hash = Column(String(130), nullable=True)
    fee_swept_at = Column(DateTime(timezone=True), nullable=True)
    merchant_sweep_amount = Column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_intent_merchant_status", "merchant_id", "status"),
        Index("ix_intent_status_expires", "status", "expires_at"),
    )


# ═══════════════════════════════════════════════════════════════
#  MerchantWebhook — URL registrati per notifiche
# ═══════════════════════════════════════════════════════════════

class MerchantWebhook(Base):
    __tablename__ = "merchant_webhooks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(64), nullable=False, index=True)

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
        if v is not None:
            import re
            if not re.match(r"^0x[a-fA-F0-9]{40}$", v):
                raise ValueError("recipient deve essere un indirizzo Ethereum valido")
            return v.lower()
        return v

    @field_validator("expected_sender")
    @classmethod
    def validate_expected_sender(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            import re
            if not re.match(r"^0x[a-fA-F0-9]{40}$", v):
                raise ValueError("expected_sender deve essere un indirizzo Ethereum valido")
            return v.lower()
        return v


class PaymentIntentResponse(BaseModel):
    intent_id: str
    reference_id: str
    deposit_address: Optional[str] = None
    amount: float
    currency: str
    chain: str = "BASE"
    recipient: Optional[str]
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
    sweep_tx_hash: Optional[str] = None
    swept_at: Optional[str] = None
    fee_bps: Optional[int] = None
    fee_amount: Optional[str] = None
    fee_tx_hash: Optional[str] = None
    merchant_sweep_amount: Optional[str] = None
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
    "payment.cancelled",
    "payment.partial",
    "payment.overpaid",
    "payment.ambiguous",
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
    deposit_address: Optional[str] = None
    amount: float
    currency: str
    chain: str = "BASE"
    status: str
    tx_hash: Optional[str]
    matched_tx_hash: Optional[str] = None
    metadata: Optional[dict]
    completed_late: Optional[bool] = None
    late_minutes: Optional[int] = None
    amount_received: Optional[str] = None
    overpaid_amount: Optional[str] = None
    underpaid_amount: Optional[str] = None
    sweep_tx_hash: Optional[str] = None
    swept_at: Optional[str] = None
    created_at: str
    completed_at: Optional[str]


class MerchantTransactionListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    records: list[MerchantTransactionItem]
