"""Pydantic schemas for email+password auth endpoints."""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
import re

from pydantic import BaseModel, Field, field_validator


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(min_length=1, max_length=100)
    terms_accepted: bool
    # Required, no default — server-side validation rejects any other value
    # with a 422. Mirrors the DB CHECK constraint ck_users_account_type.
    account_type: Literal["individual", "merchant"]

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("invalid_email_format")
        return v

    @field_validator("terms_accepted")
    @classmethod
    def _must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("terms_not_accepted")
        return v


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class ResendVerificationRequest(BaseModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class PasswordResetRequest(BaseModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class PasswordResetComplete(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    new_password: str = Field(min_length=10, max_length=256)


class SignupResponse(BaseModel):
    user_id: UUID
    email: str
    email_verified: bool
    account_type: str
    display_name: Optional[str] = None
    created_at: datetime


class CheckEmailResponse(BaseModel):
    exists: bool
    has_google: bool
    has_password: bool
    has_github: bool


class LoginResponse(BaseModel):
    access_token: str
    expires_in: int
    user_id: UUID
    email: str
    email_verified: bool
