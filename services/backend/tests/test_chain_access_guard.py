"""Central chain classification guard (unit level).

One function classifies chain ids testnet vs mainnet and enforces org access:
testnet requires onboarding_status == 'company_submitted'; mainnet
additionally requires activation_status == 'active'. Unknown chain ids
classify as mainnet (fail-closed). No mainnet chain is configured today, so
this is enforced and tested at the guard level, not end-to-end.
"""

import pytest


def test_testnet_membership():
    from app.services.chain_access import TESTNET_CHAIN_IDS, is_testnet_chain

    assert 84532 in TESTNET_CHAIN_IDS  # Base Sepolia
    assert is_testnet_chain(84532) is True
    assert is_testnet_chain(8453) is False  # Base mainnet
    assert is_testnet_chain(999_999_999) is False  # unknown -> mainnet (fail-closed)


def test_security_auth_reuses_single_definition():
    from app.security import auth as security_auth
    from app.services import chain_access

    assert security_auth.TESTNET_CHAIN_IDS is chain_access.TESTNET_CHAIN_IDS


def test_chain_name_mapping():
    from app.services.chain_access import CHAIN_ID_BY_NAME

    assert CHAIN_ID_BY_NAME["base_sepolia"] == 84532
    assert CHAIN_ID_BY_NAME["base"] == 8453


# ── Access matrix ─────────────────────────────────────────────────

def _check(onboarding, activation, chain_id):
    from app.services.chain_access import check_org_chain_access

    return check_org_chain_access(onboarding, activation, chain_id)


def test_testnet_allowed_once_company_submitted():
    _check("company_submitted", "not_started", 84532)  # no raise


@pytest.mark.parametrize("onboarding", ["created", "email_verified"])
def test_testnet_denied_before_company_submitted(onboarding):
    from app.services.chain_access import ChainAccessError

    with pytest.raises(ChainAccessError) as exc:
        _check(onboarding, "not_started", 84532)
    assert exc.value.code == "company_profile_required"


def test_mainnet_requires_active_activation():
    from app.services.chain_access import ChainAccessError

    with pytest.raises(ChainAccessError) as exc:
        _check("company_submitted", "not_started", 8453)
    assert exc.value.code == "mainnet_activation_required"


@pytest.mark.parametrize("activation", ["kyb_pending", "rejected"])
def test_mainnet_denied_for_non_active_states(activation):
    from app.services.chain_access import ChainAccessError

    with pytest.raises(ChainAccessError):
        _check("company_submitted", activation, 8453)


def test_mainnet_allowed_when_active():
    _check("company_submitted", "active", 8453)  # no raise


def test_onboarding_gate_precedes_activation_even_on_mainnet():
    from app.services.chain_access import ChainAccessError

    with pytest.raises(ChainAccessError) as exc:
        _check("email_verified", "active", 8453)
    assert exc.value.code == "company_profile_required"


def test_unknown_chain_id_treated_as_mainnet():
    from app.services.chain_access import ChainAccessError

    with pytest.raises(ChainAccessError) as exc:
        _check("company_submitted", "not_started", 123456789)
    assert exc.value.code == "mainnet_activation_required"
