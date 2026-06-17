"""Pydantic schemas for email+password auth endpoints."""

from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID
import re

from pydantic import BaseModel, Field, field_validator

from app.constants.countries import is_valid_country


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=256)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    # ISO 8601 date (YYYY-MM-DD); server enforces age >= 18 → 422 if under.
    date_of_birth: date
    # ISO 3166-1 alpha-2; validated against the official set → 422 if invalid.
    country_of_residence: str = Field(min_length=2, max_length=2)
    # Required, no default — server-side validation rejects any other value
    # with a 422. Mirrors the DB CHECK constraint ck_users_account_type.
    account_type: Literal["individual", "merchant"]
    terms_accepted: bool
    # Optional marketing opt-in.
    newsletter_opt_in: bool = False
    # display_name is derived server-side from first+last when omitted; kept
    # optional for backward compatibility.
    display_name: Optional[str] = Field(default=None, max_length=100)
    # UI locale for building the verification link; clamped server-side to a
    # supported locale (default 'en'). Optional.
    locale: Optional[str] = Field(default=None, max_length=10)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("invalid_email_format")
        return v

    @field_validator("first_name", "last_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name_required")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def _must_be_adult(cls, v: date) -> date:
        today = date.today()
        if v > today:
            raise ValueError("invalid_dob")
        age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
        if age < 18:
            raise ValueError("under_18")
        return v

    @field_validator("country_of_residence")
    @classmethod
    def _valid_country(cls, v: str) -> str:
        v = v.strip().upper()
        if not is_valid_country(v):
            raise ValueError("invalid_country")
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
