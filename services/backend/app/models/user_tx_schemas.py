"""Pydantic schemas for /api/v1/user/transactions CRUD + bulk-import + paging."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


TxType = Literal[
    "transfer", "swap", "approve", "wrap", "unwrap", "split", "bridge"
]
TxStatus = Literal[
    "pending", "confirming", "confirmed", "failed", "cancelled"
]
TxDirection = Literal["out", "in"]


class TransactionCreate(BaseModel):
    chain_id: int
    tx_hash: str = Field(min_length=66, max_length=66)
    wallet_address: str
    tx_type: TxType
    tx_status: TxStatus = "pending"
    direction: TxDirection = "out"
    token_symbol: Optional[str] = None
    token_address: Optional[str] = None
    amount_raw: Optional[str] = None
    amount_decimal: Optional[Decimal] = None
    counterparty_address: Optional[str] = None
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)
    submitted_at: Optional[datetime] = None


class TransactionUpdate(BaseModel):
    tx_status: Optional[TxStatus] = None
    gas_used: Optional[int] = None
    gas_price_gwei: Optional[Decimal] = None
    block_number: Optional[int] = None
    confirmed_at: Optional[datetime] = None
    extra_metadata: Optional[Dict[str, Any]] = None


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chain_id: int
    tx_hash: str
    wallet_address: str
    tx_type: str
    tx_status: str
    direction: str
    token_symbol: Optional[str]
    token_address: Optional[str]
    amount_raw: Optional[str]
    amount_decimal: Optional[Decimal]
    counterparty_address: Optional[str]
    extra_metadata: Dict[str, Any]
    gas_used: Optional[int]
    gas_price_gwei: Optional[Decimal]
    block_number: Optional[int]
    submitted_at: datetime
    confirmed_at: Optional[datetime]
    updated_at: datetime


class BulkImportRequest(BaseModel):
    transactions: List[TransactionCreate] = Field(max_length=500)


class BulkImportError(BaseModel):
    tx_hash: str
    error: str


class BulkImportResponse(BaseModel):
    imported: int
    skipped: int
    errors: List[BulkImportError]


class PaginatedTransactions(BaseModel):
    items: List[TransactionResponse]
    next_cursor: Optional[str]
    has_more: bool
