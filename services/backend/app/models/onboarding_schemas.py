"""Pydantic schemas for the staged-onboarding endpoints.

Server-side validation always: bounded lengths, whitelisted enums (Literal),
ISO 3166-1 alpha-2 country codes via the official set, http(s)-only website
URL. Reject, never coerce (uppercasing a country code is normalization of an
otherwise-valid value, matching SignupRequest). Columns store plain text —
the enums are enforced HERE.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.constants.countries import is_valid_country

BusinessCategory = Literal[
    "ecommerce",
    "saas",
    "marketplace",
    "professional_services",
    "legal_corporate_services",
    "travel",
    "education",
    "gaming",
    "nonprofit",
    "other",
]

# Expected monthly volume bands, in EUR.
VolumeBand = Literal["lt_10k", "10k_100k", "100k_1m", "gt_1m"]

Stablecoin = Literal["USDC", "USDT", "EURC"]


class CompanyProfilePatch(BaseModel):
    """Draft autosave payload — every field optional (partial PATCH)."""

    legal_name: Optional[str] = Field(None, min_length=1, max_length=200)
    trading_name: Optional[str] = Field(None, max_length=200)
    country: Optional[str] = Field(None, min_length=2, max_length=2)
    registration_number: Optional[str] = Field(None, min_length=1, max_length=100)
    tax_or_vat_number: Optional[str] = Field(None, min_length=1, max_length=100)
    website: Optional[str] = Field(None, max_length=2048)
    business_category: Optional[BusinessCategory] = None
    expected_monthly_volume: Optional[VolumeBand] = None
    countries_served: Optional[list[str]] = Field(None, max_length=250)
    primary_stablecoin: Optional[Stablecoin] = None
    no_sanctioned_countries: Optional[bool] = None
    no_prohibited_activities: Optional[bool] = None
    has_pep: Optional[bool] = None

    @field_validator("country")
    @classmethod
    def _valid_country(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().upper()
        if not is_valid_country(v):
            raise ValueError("invalid_country")
        return v

    @field_validator("countries_served")
    @classmethod
    def _valid_countries_served(
        cls, v: Optional[list[str]]
    ) -> Optional[list[str]]:
        if v is None:
            return v
        normalized = []
        for code in v:
            code = code.strip().upper()
            if not is_valid_country(code):
                raise ValueError("invalid_country")
            normalized.append(code)
        return normalized

    @field_validator("website")
    @classmethod
    def _valid_website(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("invalid_url")
        return v


class CompanyProfileResponse(BaseModel):
    legal_name: Optional[str] = None
    trading_name: Optional[str] = None
    country: Optional[str] = None
    registration_number: Optional[str] = None
    tax_or_vat_number: Optional[str] = None
    website: Optional[str] = None
    business_category: Optional[str] = None
    expected_monthly_volume: Optional[str] = None
    countries_served: Optional[list[str]] = None
    primary_stablecoin: Optional[str] = None
    no_sanctioned_countries: Optional[bool] = None
    no_prohibited_activities: Optional[bool] = None
    has_pep: Optional[bool] = None
    submitted_at: Optional[datetime] = None


class CompanyProfileState(BaseModel):
    exists: bool
    submitted_at: Optional[datetime] = None


class OnboardingStateResponse(BaseModel):
    consents_current: bool
    age_attested: bool
    email_verified: bool
    active_org_id: Optional[str] = None
    onboarding_status: Optional[str] = None
    activation_status: Optional[str] = None
    approval_status: Optional[str] = None
    decline_reason: Optional[str] = None
    company_profile: Optional[CompanyProfileState] = None


class ConsentSubmitRequest(BaseModel):
    """The two interstitial checkboxes — both must be checked to proceed."""

    accept_documents: bool
    age_attested: bool

    @field_validator("accept_documents")
    @classmethod
    def _must_accept_documents(cls, v: bool) -> bool:
        if not v:
            raise ValueError("documents_not_accepted")
        return v

    @field_validator("age_attested")
    @classmethod
    def _must_attest_age(cls, v: bool) -> bool:
        if not v:
            raise ValueError("age_not_attested")
        return v
