"""Static pin: the BACKEND signs nothing, and the KEEPER can only pay gas.

Non-custodial is the load-bearing product invariant (see CLAUDE.md). The split
feature reintroduces classic Flow's *split* — deliberately WITHOUT its
custodial machinery (Master/hot wallet, key_manager, nonce_manager,
sweep_service, split_executor, oracle co-sign, backend-signed payouts). This
test pins that state so a future change reintroducing any of it fails loudly.

Two roots, two different rules, because there are now two different claims.

── services/backend/app — signs NOTHING ─────────────────────────────
Unchanged. Allowed and explicitly NOT flagged: signature VERIFICATION (SIWE /
wallet auth recover via eth_account.Account.recover_message) — verifying is not
signing. `rpc_manager.send_raw_transaction` is a dormant zero-caller helper; the
pin forbids CALLERS, not the helper itself.

── services/keeper — signs, but can only pay gas ────────────────────
The Auto Split keeper holds a private key. That is a deliberate, reviewed
exception to "RSends signs nothing", and it is bounded by the SHAPE of what it
can send rather than by trust: `executeSplit(merchant, token)` takes no
destination and no amount, so the account can trigger a merchant's own published
policy or waste gas, and nothing else.

Without the rules below, this file would keep passing while its own headline
sentence became false repo-wide — it only ever looked at `app/`. So the keeper
root pins the authority boundary directly:

  1. `Account.from_key` in exactly ONE module — key handling has one site.
  2. build/sign/broadcast in that same ONE module.
  3. that module names exactly ONE contract method: `executeSplit`.
  4. no fund-moving ERC-20 or policy-writing method anywhere in the keeper —
     `approve`/`transfer` belong to the merchant's key, and `setPolicy`
     /`clearPolicy` are how they decide where money goes.

Rule 3 is what makes rule 1 safe: a method the keeper cannot name is a method it
cannot call, so the key's authority is bounded by this file rather than by the
current contents of a function body.
"""

import re
from pathlib import Path

from tests._source_helpers import source_without_prose

APP = Path(__file__).resolve().parents[1] / "app"
#: A sibling SERVICE, not a package of this one — scanned by path because it is
#: deliberately not importable from here.
KEEPER = Path(__file__).resolve().parents[2] / "keeper" / "keeper"

#: The single keeper module allowed to hold the key and broadcast.
KEEPER_SIGNER_MODULE = "executor.py"

#: The only contract method the keeper's signer may name.
KEEPER_ALLOWED_SEND = "executeSplit"

#: Methods that move a merchant's money or redirect where it goes. None of them
#: is the keeper's to call, on any chain, ever.
KEEPER_FORBIDDEN_METHODS = (
    "approve",
    "transfer",
    "transferFrom",
    "setPolicy",
    "clearPolicy",
    "paySplit",
    "payWithPermit",
)

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


# ═══════════════════════════════════════════════════════════════
#  services/keeper — the gas-only exception, bounded
# ═══════════════════════════════════════════════════════════════
#
# Prose is stripped for THIS root only. The backend rules above are a raw text
# scan on purpose (nothing there should mention signing at all), but the keeper
# modules explain at length what they may not do, and a guard that fires on its
# own explanation teaches people to delete the explanation.


def _keeper_files():
    if not KEEPER.is_dir():
        return []
    return sorted(p for p in KEEPER.rglob("*.py") if "__pycache__" not in p.parts)


def _keeper_code(path: Path) -> str:
    return source_without_prose(path.read_text(encoding="utf-8", errors="replace"))


def test_keeper_source_is_present_to_scan():
    """A guard that silently scans nothing passes forever. If the keeper moves,
    this fails instead of quietly covering an empty directory."""
    assert _keeper_files(), (
        f"no keeper modules found under {KEEPER} — if the service moved, move "
        "this pin with it rather than letting it scan nothing"
    )


def test_only_one_keeper_module_holds_the_key_and_broadcasts():
    """Key handling and broadcasting have exactly one site, so reviewing the
    keeper's authority means reviewing one file."""
    patterns = (
        r"\bAccount\.from_key\b",
        r"\bsign_transaction\b",
        r"\bsend_raw_transaction\b",
        r"\bbuild_transaction\b",
    )
    offenders = []
    for path in _keeper_files():
        if path.name == KEEPER_SIGNER_MODULE:
            continue
        code = _keeper_code(path)
        for pattern in patterns:
            if re.search(pattern, code):
                offenders.append(f"{path.name} matches {pattern}")
    assert offenders == [], (
        "only "
        f"{KEEPER_SIGNER_MODULE} may hold the key or broadcast: " + "; ".join(offenders)
    )


def test_the_keeper_signer_can_send_only_executeSplit():
    """The authority boundary itself. `executeSplit(merchant, token)` carries no
    destination and no amount, so this one name is the difference between a key
    that can pay gas and a key that can move money."""
    signer = KEEPER / KEEPER_SIGNER_MODULE
    assert signer.is_file(), f"{signer} is missing — has the signer been renamed?"

    named = set(re.findall(r"\.functions\.(\w+)", _keeper_code(signer)))

    assert named == {KEEPER_ALLOWED_SEND}, (
        f"{KEEPER_SIGNER_MODULE} names contract methods {sorted(named)}; only "
        f"{KEEPER_ALLOWED_SEND!r} is permitted — a keeper that can name a second "
        "method is a keeper whose key can do a second thing"
    )


def test_the_keeper_never_names_a_fund_moving_method():
    """`approve` and `transfer` belong to the merchant's key — `approve(spender,
    0)` is their trustless brake, and the keeper must be unable to undo or
    re-grant it. `setPolicy`/`clearPolicy` are how they choose recipients."""
    offenders = []
    for path in _keeper_files():
        code = _keeper_code(path)
        for method in KEEPER_FORBIDDEN_METHODS:
            if re.search(rf"\.functions\.{method}\b", code):
                offenders.append(f"{path.name} calls {method}")
    assert offenders == [], "\n".join(offenders)
