"""Signup request validation: account_type, profile fields (name/DOB/country),
newsletter, derived display_name, and verification-link locale clamping."""

import pytest
from pydantic import ValidationError

from app.models.email_auth_schemas import SignupRequest
from app.services.email_auth_service import _safe_locale


_BASE = dict(
    email="a@b.com",
    password="longenough123",
    first_name="Ada",
    last_name="Lovelace",
    date_of_birth="1990-05-01",
    country_of_residence="IT",
    account_type="individual",
    terms_accepted=True,
)


# ── account_type ──
def test_account_type_required():
    base = {k: v for k, v in _BASE.items() if k != "account_type"}
    with pytest.raises(ValidationError):
        SignupRequest(**base)


def test_account_type_rejects_unknown_value():
    with pytest.raises(ValidationError):
        SignupRequest(**{**_BASE, "account_type": "enterprise"})


@pytest.mark.parametrize("value", ["individual", "merchant"])
def test_account_type_accepts_allowed_values(value):
    assert SignupRequest(**{**_BASE, "account_type": value}).account_type == value


# ── profile fields ──
def test_valid_adult_ok():
    req = SignupRequest(**_BASE)
    assert req.first_name == "Ada" and req.last_name == "Lovelace"
    assert req.country_of_residence == "IT"
    assert req.display_name is None  # derived server-side, optional in the request
    assert req.newsletter_opt_in is False  # optional default


def test_country_is_uppercased():
    assert SignupRequest(**{**_BASE, "country_of_residence": "it"}).country_of_residence == "IT"


def test_under_18_rejected():
    with pytest.raises(ValidationError):
        SignupRequest(**{**_BASE, "date_of_birth": "2015-01-01"})


def test_future_dob_rejected():
    with pytest.raises(ValidationError):
        SignupRequest(**{**_BASE, "date_of_birth": "2999-01-01"})


def test_invalid_country_rejected():
    with pytest.raises(ValidationError):
        SignupRequest(**{**_BASE, "country_of_residence": "ZZ"})


def test_blank_name_rejected():
    with pytest.raises(ValidationError):
        SignupRequest(**{**_BASE, "first_name": "   "})


def test_newsletter_opt_in_accepted():
    assert SignupRequest(**{**_BASE, "newsletter_opt_in": True}).newsletter_opt_in is True


# ── locale clamp ──
def test_locale_is_optional():
    assert SignupRequest(**_BASE).locale is None


def test_safe_locale_clamps_unknown_to_en():
    assert _safe_locale(None) == "en"
    assert _safe_locale("") == "en"
    assert _safe_locale("xx") == "en"
    assert _safe_locale("../etc") == "en"


@pytest.mark.parametrize("loc", ["en", "it", "es", "fr", "de"])
def test_safe_locale_passes_supported(loc):
    assert _safe_locale(loc) == loc
