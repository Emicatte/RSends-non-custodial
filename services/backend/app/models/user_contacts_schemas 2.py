"""Pydantic schemas for /api/v1/user/contacts CRUD + bulk-import."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ContactCreate(BaseModel):
    address: str = Field(min_length=10, max_length=128)
    label: str = Field(min_length=0, max_length=200)
    last_used_at: Optional[datetime] = None
    tx_count: int = Field(default=0, ge=0)
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)


class ContactUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)
    last_used_at: Optional[datetime] = None
    tx_count: Optional[int] = Field(default=None, ge=0)
    extra_metadata: Optional[Dict[str, Any]] = None


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    address: str
    label: str
    last_used_at: Optional[datetime]
    tx_count: int
    extra_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class BulkImportContactsRequest(BaseModel):
    contacts: List[ContactCreate] = Field(max_length=1000)


class BulkImportContactError(BaseModel):
    address: str
    error: str


class BulkImportContactsResponse(BaseModel):
    imported: int
    skipped: int
    errors: List[BulkImportContactError]
