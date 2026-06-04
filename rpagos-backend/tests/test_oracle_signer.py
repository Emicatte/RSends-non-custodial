"""M1 — internal oracle digest signer (slice A KMS remote signing + slice B multisig).

Verifies the /api/internal/oracle/sign-digest endpoint signs a 32-byte EIP-712
digest with the dedicated oracle signer set, that a single-signer result is
byte-identical to signing with that key (deterministic RFC-6979), that a 2-of-N
set returns signatures sorted ascending by signer address (V5/V6 order), and
that the X-Internal-Secret gate (H3) holds. No KMS/AWS needed.
"""

from eth_account import Account
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services.key_manager as km
from app.api.oracle_signer_routes import oracle_signer_router

# Well-known dev keys (Anvil #1 / #2) — local mode only.
TEST_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
TEST_KEY2 = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
DIGEST = "0x" + "ab" * 32  # arbitrary 32-byte digest


class _SignerSettings:
    oracle_signer_mode = "local"
    oracle_signer_private_key = TEST_KEY
    oracle_signer_private_keys = ""
    oracle_kms_key_id = ""
    oracle_kms_key_ids = ""
    sweep_private_key = ""


class _MultiSignerSettings:
    oracle_signer_mode = "local"
    oracle_signer_private_key = ""
    oracle_signer_private_keys = f"{TEST_KEY},{TEST_KEY2}"
    oracle_kms_key_id = ""
    oracle_kms_key_ids = ""
    sweep_private_key = ""


class _SecretSettings:
    internal_proxy_secret = "topsecret"
    debug = False


def _client(monkeypatch, signer_settings=None):
    km._oracle_signers = None  # reset the cached signer set between tests
    monkeypatch.setattr(
        "app.services.key_manager.get_settings",
        lambda: signer_settings or _SignerSettings(),
    )
    monkeypatch.setattr("app.api.signing_routes.get_settings", lambda: _SecretSettings())
    app = FastAPI()
    app.include_router(oracle_signer_router)
    return TestClient(app, raise_server_exceptions=False)


def _expected_signature(key: str) -> str:
    signed = Account.from_key(key).unsafe_sign_hash(bytes.fromhex(DIGEST[2:]))
    v = signed.v if signed.v >= 27 else signed.v + 27
    return "0x" + signed.r.to_bytes(32, "big").hex() + signed.s.to_bytes(32, "big").hex() + bytes([v]).hex()


def test_sign_digest_matches_local_signature(monkeypatch):
    c = _client(monkeypatch)
    r = c.post(
        "/api/internal/oracle/sign-digest",
        headers={"X-Internal-Secret": "topsecret"},
        json={"digest": DIGEST},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    expected_addr = Account.from_key(TEST_KEY).address
    assert body["signer_address"].lower() == expected_addr.lower()
    assert body["signature"] == _expected_signature(TEST_KEY)
    # Single signer → signatures has one element equal to the primary.
    assert body["signatures"] == [body["signature"]]
    assert body["signer_addresses"] == [body["signer_address"]]
    assert len(bytes.fromhex(body["signature"][2:])) == 65


def test_multisign_sorted_ascending(monkeypatch):
    c = _client(monkeypatch, _MultiSignerSettings())
    r = c.post(
        "/api/internal/oracle/sign-digest",
        headers={"X-Internal-Secret": "topsecret"},
        json={"digest": DIGEST},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    addr1 = Account.from_key(TEST_KEY).address
    addr2 = Account.from_key(TEST_KEY2).address
    expected_order = sorted([addr1, addr2], key=lambda a: int(a, 16))

    assert len(body["signatures"]) == 2
    assert [a.lower() for a in body["signer_addresses"]] == [a.lower() for a in expected_order]
    # Each signature recovers to its claimed signer (and matches the local sig).
    by_key = {addr1.lower(): TEST_KEY, addr2.lower(): TEST_KEY2}
    for addr, sig in zip(body["signer_addresses"], body["signatures"]):
        assert sig == _expected_signature(by_key[addr.lower()])
    # Primary == signatures[0] (V4 back-compat).
    assert body["signature"] == body["signatures"][0]


def test_requires_internal_secret(monkeypatch):
    c = _client(monkeypatch)
    assert c.post("/api/internal/oracle/sign-digest", json={"digest": DIGEST}).status_code == 403
    assert c.post(
        "/api/internal/oracle/sign-digest",
        headers={"X-Internal-Secret": "nope"},
        json={"digest": DIGEST},
    ).status_code == 403


def test_rejects_bad_digest(monkeypatch):
    c = _client(monkeypatch)
    r = c.post(
        "/api/internal/oracle/sign-digest",
        headers={"X-Internal-Secret": "topsecret"},
        json={"digest": "0xabcd"},  # 2 bytes, not 32
    )
    assert r.status_code == 422
