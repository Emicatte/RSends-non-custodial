"""Static pin: NO operational code path signs or moves funds from an
RSends-held key.

Non-custodial is the load-bearing product invariant (see CLAUDE.md). The split
feature reintroduces classic Flow's *split* — deliberately WITHOUT its
custodial machinery (Master/hot wallet, key_manager, nonce_manager,
sweep_service, split_executor, oracle co-sign, backend-signed payouts). This
test pins that state so a future change reintroducing any of it fails loudly.

Allowed and explicitly NOT flagged: signature VERIFICATION (SIWE / wallet auth
recover via eth_account.Account.recover_message) — verifying is not signing.
`rpc_manager.send_raw_transaction` is a dormant zero-caller helper; the pin
forbids CALLERS, not the helper itself.
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# Module (file) names that existed only in the custodial architecture.
FORBIDDEN_MODULES = {
    "key_manager.py",
    "nonce_manager.py",
    "sweep_service.py",
    "deposit_sweep_service.py",
    "split_executor.py",
    "split_engine.py",       # classic's server-side split — ours is on-chain only
    "wallet_manager.py",
    "oracle_signer.py",
    "execution_engine.py",
    "distribution_service.py",
}

# Source patterns that only appear when the backend SIGNS or holds keys.
FORBIDDEN_PATTERNS = [
    r"\bAccount\.from_key\b",        # loading a private key into memory
    r"\bsign_transaction\b",         # signing a fund-moving tx
    r"\bsignTransaction\b",
    r"\bKMSSigner\b",
    r"\bLocalSigner\b",
    r"\bsend_raw_transaction\s*\(",  # broadcasting a (necessarily signed) tx
]


def _py_files():
    return [p for p in APP.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_custodial_modules_exist():
    present = sorted(
        str(p.relative_to(APP)) for p in _py_files() if p.name in FORBIDDEN_MODULES
    )
    assert present == [], f"custodial modules reintroduced: {present}"


def test_no_code_signs_or_broadcasts_from_a_backend_key():
    offenders = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in FORBIDDEN_PATTERNS:
            for m in re.finditer(pattern, text):
                # The dormant helper's own definition in rpc_manager is allowed;
                # any CALLER of it anywhere else is not.
                if (
                    pattern.startswith(r"\bsend_raw_transaction")
                    and path.name == "rpc_manager.py"
                ):
                    continue
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(APP)}:{line} matches {pattern}")
    assert offenders == [], "\n".join(offenders)
