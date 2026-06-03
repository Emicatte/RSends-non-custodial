"""account_type validation on signup + verification-link locale clamping."""

import pytest
from pydantic import ValidationError

from app.models.email_auth_schemas import SignupRequest
from app.services.email_auth_service import _safe_locale


_BASE = dict(
    email="a@b.com",
    password="longenough123",
    display_name="Alice",
    terms_accepted=True,
)


def test_account_type_required():
    with pytest.raises(ValidationError):
        SignupRequest(**_BASE)


def test_account_type_rejects_unknown_value():
    with pytest.raises(ValidationError):
        SignupRequest(**_BASE, account_type="enterprise")


@pytest.mark.parametrize("value", ["individual", "merchant"])
def test_account_type_accepts_allowed_values(value):
    req = SignupRequest(**_BASE, account_type=value)
    assert req.account_type == value


def test_locale_is_optional():
    req = SignupRequest(**_BASE, account_type="individual")
    assert req.locale is None


def test_safe_locale_clamps_unknown_to_en():
    assert _safe_locale(None) == "en"
    assert _safe_locale("") == "en"
    assert _safe_locale("xx") == "en"
    assert _safe_locale("../etc") == "en"


@pytest.mark.parametrize("loc", ["en", "it", "es", "fr", "de"])
def test_safe_locale_passes_supported(loc):
    assert _safe_locale(loc) == loc
