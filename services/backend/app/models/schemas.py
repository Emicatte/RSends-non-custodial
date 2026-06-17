"""
RPagos Backend Core — Pydantic Schemas.

Mappatura esatta del payload generato da TransactionStatus.tsx v3.
Ogni campo è documentato con il nome corrispondente nel frontend.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import re


# ═══════════════════════════════════════════════════════════════
#  Request: POST /api/v1/tx/callback
# ═══════════════════════════════════════════════════════════════

class ComplianceRecordPayload(BaseModel):
    """Mappa il tipo ComplianceRecord importato in TransactionStatus.tsx."""

    compliance_id: str = Field(..., min_length=8, description="UUID compliance")
    block_timestamp: str = Field(..., description="ISO timestamp del blocco")
    fiat_rate: Optional[float] = Field(None, ge=0, description="Tasso 1 CRYPTO = X EUR")
    asset: str = Field(..., max_length=16, description="Simbolo: USDC, ETH, ecc.")
    fiat_gross: Optional[float] = Field(None, ge=0, description="Controvalore EUR lordo")
    ip_jurisdiction: str = Field(..., max_length=8, description="Codice paese: IT, DE…")
    mica_applicable: bool = Field(False, description="Se MiCA è applicabile")
    fiscal_ref: str = Field(..., description="Riferimento fiscale unico")
    network: str = Field(..., description="BASE, BASE_SEPOLIA, ecc.")


class TransactionCallbackPayload(BaseModel):
    """
    Payload completo del callback — esattamente i props di TransactionStatusUI:

    Frontend field      →  Backend field
    ─────────────────────────────────────
    txHash              →  tx_hash
    grossStr            →  gross_amount (parsato a float)
    netStr              →  net_amount
    feeStr              →  fee_amount
    symbol              →  currency
    recipient           →  recipient
    paymentRef          →  payment_ref
    fiscalRef           →  fiscal_ref
    eurValue            →  eur_value (parsato a float)
    timestamp           →  timestamp
    isTestnet           →  is_testnet
    complianceRecord    →  compliance_record
    x_signature         →  x_signature (HMAC SHA-256)
    """

    # Identificativi
    fiscal_ref: str = Field(..., min_length=4, description="Identificativo unico fiscale")
    payment_ref: Optional[str] = Field(None, description="Riferimento interno pagamento")
    tx_hash: str = Field(..., min_length=66, max_length=66, description="Hash TX on-chain 0x...")

    # Importi — il frontend manda stringhe, qui validati come float
    gross_amount: float = Field(..., gt=0, description="Importo lordo (grossStr)")
    net_amount: float = Field(..., gt=0, description="Importo netto 99.5% (netStr)")
    fee_amount: float = Field(..., ge=0, description="Fee 0.5% (feeStr)")
    currency: str = Field(..., max_length=16, description="Simbolo: USDC, ETH")
    eur_value: Optional[float] = Field(None, ge=0, description="Controvalore EUR")

    # Rete
    network: str = Field(..., description="BASE_MAINNET o BASE_SEPOLIA")
    is_testnet: bool = Field(False, description="Flag testnet dal frontend")
    recipient: Optional[str] = Field(None, max_length=42, description="Indirizzo destinatario")

    # Stato
    status: str = Field("completed", description="completed | failed | cancelled")

    # Timestamp
    timestamp: datetime = Field(..., description="Quando la TX è stata confermata")

    # Sicurezza
    x_signature: str = Field(..., min_length=16, description="HMAC SHA-256 firma del payload")

    # Idempotency (opzionale — se presente, abilita idempotency check)
    idempotency_key: Optional[str] = Field(
        None, max_length=128, description="Chiave di idempotenza per prevenire doppia esecuzione"
    )

    # Compliance record opzionale
    compliance_record: Optional[ComplianceRecordPayload] = None

    @field_validator("tx_hash")
    @classmethod
    def validate_tx_hash(cls, v: str) -> str:
        if not re.match(r"^0x[a-fA-F0-9]{64}$", v):
            raise ValueError("tx_hash deve essere un hash esadecimale 0x + 64 caratteri")
        return v.lower()

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(r"^0x[a-fA-F0-9]{40}$", v):
            raise ValueError("recipient deve essere un indirizzo Ethereum valido")
        return v.lower() if v else v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"completed", "failed", "pending", "cancelled"}
        if v not in allowed:
            raise ValueError(f"status deve essere uno di: {allowed}")
        return v

    @field_validator("network")
    @classmethod
    def validate_network(cls, v: str) -> str:
        allowed = {"BASE_MAINNET", "BASE_SEPOLIA", "BASE"}
        if v not in allowed:
            raise ValueError(f"network deve essere uno di: {allowed}")
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        allowed = {"ETH", "USDC", "USDT", "DAI", "cbBTC", "DEGEN"}
        if v not in allowed:
            raise ValueError(f"currency deve essere uno di: {allowed}")
        return v


# ═══════════════════════════════════════════════════════════════
#  Responses
# ═══════════════════════════════════════════════════════════════

class CallbackResponse(BaseModel):
    status: str = "success"
    message: str
    transaction_id: int
    compliance_logged: bool = False
    matched_intent_id: Optional[str] = None
    webhook_triggered: bool = False
    matching: Optional[str] = None       # "queued" | "inline" | None (no match attempted)


class AnomalyAlertResponse(BaseModel):
    anomaly_type: str
    z_score: float
    description: str
    window_start: datetime
    window_end: datetime
    affected_tx_count: int


class AnomalyReportResponse(BaseModel):
    total_transactions: int
    anomalies_found: int
    alerts: list[AnomalyAlertResponse]
    analysis_window_hours: int
