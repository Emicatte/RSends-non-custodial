"""Indexer hardening (Phase B, B3/B4): a PaymentMade matched to an intent with
NO recipient must FAIL validation (recorded rejected downstream), not silently
skip the merchant check. Post-gate an empty recipient can only be a pre-gate
legacy row whose /pay link never worked; settling it against an arbitrary payee
would be wrong.

Unit tests of `_validate_event_against_intent` with a SimpleNamespace intent —
an unregistered currency makes token_for() None so only the merchant check runs.
"""

from types import SimpleNamespace

from app.services.payment_indexer import _validate_event_against_intent

MERCHANT = "0x1111111111111111111111111111111111111111"


def _ev(merchant=MERCHANT, token="0x" + "2" * 40, amount=100):
    return {"merchant": merchant, "token": token, "amount": amount}


def _intent(recipient):
    # Unregistered currency → token_for() None → token/amount checks skipped,
    # isolating the merchant/recipient check.
    return SimpleNamespace(
        recipient=recipient, chain="base", currency="NOTATOKEN", amount=100.0
    )


def test_empty_recipient_records_reason():
    reasons = _validate_event_against_intent(_ev(), _intent(""))
    assert reasons, "empty recipient must produce a validation-failed reason"


def test_none_recipient_records_reason():
    reasons = _validate_event_against_intent(_ev(), _intent(None))
    assert reasons, "None recipient must produce a validation-failed reason"


def test_matching_recipient_passes():
    # A real recipient matching the event merchant → no reason (token skipped).
    reasons = _validate_event_against_intent(_ev(merchant=MERCHANT), _intent(MERCHANT))
    assert reasons == []


def test_mismatched_recipient_still_flagged():
    reasons = _validate_event_against_intent(
        _ev(merchant="0x" + "9" * 40), _intent(MERCHANT)
    )
    assert reasons
