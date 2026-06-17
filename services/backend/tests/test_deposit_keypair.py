"""
RPagos Backend — Deposit Keypair Derivation Tests.

Verifica che la derivazione deterministica produce keypair reali:
  1. generate_deposit_address(intent_id) -> address valido
  2. get_private_key_for_intent(intent_id) -> private key corrispondente
  3. sign(message, private_key) -> recover(signature) == address
  4. Stessa chiave per lo stesso intent_id (deterministico)
  5. Chiavi diverse per intent_id diversi

Run:
    cd rpagos-backend && python3 -m pytest tests/test_deposit_keypair.py -v

Requisiti:
    DEPOSIT_MASTER_KEY impostato in .env (0x-prefixed 64-char hex)
"""

import os
import secrets
from pathlib import Path
from unittest.mock import patch

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct


def _read_master_key() -> str:
    """Legge DEPOSIT_MASTER_KEY dal .env del backend."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("DEPOSIT_MASTER_KEY=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip("'\"")
    return os.environ.get("DEPOSIT_MASTER_KEY", "")


MASTER_KEY = _read_master_key()


@pytest.fixture(autouse=True)
def _set_master_key(monkeypatch):
    """Assicura che DEPOSIT_MASTER_KEY sia impostata per i test."""
    if not MASTER_KEY:
        pytest.skip("DEPOSIT_MASTER_KEY non impostata in .env")
    monkeypatch.setenv("DEPOSIT_MASTER_KEY", MASTER_KEY)


# ═══════════════════════════════════════════════════════════════
#  TEST 1: generate -> get_private_key -> sign -> recover
# ═══════════════════════════════════════════════════════════════

def test_generate_and_recover():
    """
    Verifica il ciclo completo:
      generate_address(intent) -> address
      get_private_key(intent) -> key
      sign(msg, key) -> signature
      recover(msg, signature) -> recovered_address == address
    """
    from app.services.deposit_address_service import (
        generate_deposit_address,
        get_private_key_for_intent,
    )

    intent_id = f"pi_test_{secrets.token_hex(12)}"

    # 1. Genera address
    address = generate_deposit_address(intent_id)
    assert address.startswith("0x"), f"Address should start with 0x, got: {address}"
    assert len(address) == 42, f"Address should be 42 chars, got: {len(address)}"

    # 2. Ricostruisci private key
    private_key = get_private_key_for_intent(intent_id)
    assert private_key.startswith("0x"), "Private key should start with 0x"
    assert len(private_key) == 66, f"Private key should be 66 chars (0x + 64 hex), got: {len(private_key)}"

    # 3. Verifica che la private key produce lo stesso address
    account = Account.from_key(private_key)
    assert account.address.lower() == address.lower(), (
        f"Address mismatch: generated={address}, from_key={account.address}"
    )

    # 4. Sign + recover
    message = encode_defunct(text="test message for deposit keypair verification")
    signed = account.sign_message(message)
    recovered = Account.recover_message(message, signature=signed.signature)

    assert recovered.lower() == address.lower(), (
        f"Recovered address mismatch: expected={address}, recovered={recovered}"
    )


# ═══════════════════════════════════════════════════════════════
#  TEST 2: Determinism — same intent_id -> same address/key
# ═══════════════════════════════════════════════════════════════

def test_deterministic():
    """Lo stesso intent_id produce sempre lo stesso address e private key."""
    from app.services.deposit_address_service import (
        generate_deposit_address,
        get_private_key_for_intent,
    )

    intent_id = "pi_deterministic_test_001"

    addr1 = generate_deposit_address(intent_id)
    addr2 = generate_deposit_address(intent_id)
    assert addr1 == addr2, "Same intent_id should produce same address"

    key1 = get_private_key_for_intent(intent_id)
    key2 = get_private_key_for_intent(intent_id)
    assert key1 == key2, "Same intent_id should produce same private key"


# ═══════════════════════════════════════════════════════════════
#  TEST 3: Uniqueness — different intent_ids -> different addresses
# ═══════════════════════════════════════════════════════════════

def test_unique_addresses():
    """Intent_id diversi producono address diversi."""
    from app.services.deposit_address_service import generate_deposit_address

    addresses = set()
    for i in range(100):
        addr = generate_deposit_address(f"pi_unique_test_{i:04d}")
        assert addr not in addresses, f"Collision at intent #{i}: {addr}"
        addresses.add(addr)

    assert len(addresses) == 100


# ═══════════════════════════════════════════════════════════════
#  TEST 4: Address is valid EVM checksummed address
# ═══════════════════════════════════════════════════════════════

def test_valid_evm_address():
    """L'address generato e' un indirizzo EVM valido con checksum."""
    from app.services.deposit_address_service import generate_deposit_address
    from eth_utils import is_checksum_address

    intent_id = f"pi_checksum_test_{secrets.token_hex(8)}"
    address = generate_deposit_address(intent_id)

    assert is_checksum_address(address), (
        f"Address should be checksummed, got: {address}"
    )


# ═══════════════════════════════════════════════════════════════
#  TEST 5: Missing DEPOSIT_MASTER_KEY raises ValueError
# ═══════════════════════════════════════════════════════════════

def test_missing_master_key(monkeypatch):
    """Senza DEPOSIT_MASTER_KEY, generate_deposit_address deve fallire."""
    from app.config import get_settings

    # Clear the lru_cache to force re-read
    get_settings.cache_clear()
    monkeypatch.setenv("DEPOSIT_MASTER_KEY", "")

    from app.services.deposit_address_service import generate_deposit_address

    with pytest.raises(ValueError, match="DEPOSIT_MASTER_KEY"):
        generate_deposit_address("pi_should_fail")

    # Restore
    get_settings.cache_clear()
    monkeypatch.setenv("DEPOSIT_MASTER_KEY", MASTER_KEY)


# ═══════════════════════════════════════════════════════════════
#  TEST 6: Private key can sign ERC-20 transfer-like data
# ═══════════════════════════════════════════════════════════════

def test_sign_transaction():
    """La private key derivata puo' firmare una transazione EVM."""
    from app.services.deposit_address_service import (
        generate_deposit_address,
        get_private_key_for_intent,
    )

    intent_id = f"pi_tx_sign_test_{secrets.token_hex(8)}"
    address = generate_deposit_address(intent_id)
    private_key = get_private_key_for_intent(intent_id)

    account = Account.from_key(private_key)

    # Simula una transazione ERC-20 transfer
    tx = {
        "to": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
        "value": 0,
        "gas": 65000,
        "gasPrice": 1_000_000_000,  # 1 gwei
        "nonce": 0,
        "chainId": 8453,  # Base mainnet
        "data": "0xa9059cbb"  # transfer(address,uint256) selector
              + "0" * 24 + "dead" + "0" * 36  # to address
              + "0" * 56 + "0f4240",  # amount (1 USDC = 1000000)
    }

    signed = account.sign_transaction(tx)
    assert signed.hash is not None, "Transaction should be signed"

    # Recover sender from signed TX
    assert account.address.lower() == address.lower()
