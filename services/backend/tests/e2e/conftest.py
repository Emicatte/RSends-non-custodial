"""
Deterministic Anvil E2E harness — fixtures.

Boots a local Anvil node, deploys the money-path stack via Foundry, wires the
backend's indexer + create-intent path + webhook delivery at it, and stands up a
local webhook receiver that verifies signatures. The on-chain calls are made the
exact way the pay page makes them (build_onchain_payment → payWithPermit / pay).

Nothing here changes contract or indexer LOGIC — it only configures the registry,
settings, and RPC pointer (data/config) for the local chain.

Run via:  make e2e-anvil   (skips cleanly if anvil/forge/web3 are unavailable).
"""

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

# ── Collect the E2E module only when the toolchain is present ─────────────────
# (anvil + forge on PATH and web3 installed). Otherwise `collect_ignore` drops the
# test file so a plain `pytest tests/` without the E2E deps never errors. The
# conftest itself must import cleanly without web3, so its import is guarded.
_HAVE_ANVIL = shutil.which("anvil") is not None
_HAVE_FORGE = shutil.which("forge") is not None
try:
    from web3 import Web3
    _HAVE_WEB3 = True
except Exception:
    Web3 = None  # type: ignore
    _HAVE_WEB3 = False

if not (_HAVE_ANVIL and _HAVE_FORGE and _HAVE_WEB3):
    collect_ignore = ["test_money_path_anvil.py"]

# ── Skip (visibly) when the toolchain exists but the HARNESS env does not ─────
# The money-path tests need RSEND_E2E_ALLOW_LOOPBACK_WEBHOOKS=1 (the SSRF egress
# guard otherwise blocks the loopback HTTP webhook receiver: scheme_not_https)
# and an isolated DB. A plain `pytest tests/` must skip them WITH A REASON —
# green-because-clean, never red-for-a-missing-harness and never silently
# dropped. `make e2e-anvil` and the CI e2e job set the flag and run them.
_HAVE_HARNESS = os.getenv("RSEND_E2E_ALLOW_LOOPBACK_WEBHOOKS") == "1"


def pytest_collection_modifyitems(config, items):
    if _HAVE_HARNESS:
        return
    skip = pytest.mark.skip(
        reason=(
            "requires the e2e harness (RSEND_E2E_ALLOW_LOOPBACK_WEBHOOKS=1 + "
            "isolated DB) — run `make e2e-anvil`"
        )
    )
    for item in items:
        if item.get_closest_marker("e2e"):
            item.add_marker(skip)

# ── Anvil deterministic dev accounts ─────────────────────────────────────────
# PUBLIC, well-known Anvil/Hardhat dev keys from the standard "test test … junk"
# mnemonic. LOCAL ONLY — these never hold real funds and must never be used on a
# real network. Hardcoding them here is safe and intentional (zero secret handling).
ANVIL_ACCOUNTS = {
    "deployer": {
        "address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        "key": "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    },
    "payer": {
        "address": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        "key": "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    },
    "merchant": {
        "address": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
        "key": "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
    },
    "feeCollector": {
        "address": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
        "key": "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
    },
}

CHAIN_ID = 31337
CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "packages" / "contracts"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def anvil():
    """Launch a local Anvil node; yield its RPC URL. Terminate on teardown."""
    port = _free_port()
    proc = subprocess.Popen(
        ["anvil", "--port", str(port), "--silent", "--chain-id", str(CHAIN_ID)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        w3 = Web3(Web3.HTTPProvider(url))
        for _ in range(100):
            try:
                if w3.is_connected() and w3.eth.block_number >= 0:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("anvil did not become ready")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


@pytest.fixture(scope="session")
def deployed(anvil):
    """Deploy RSendsRouter + 6-dec USDC(permit)/USDT(no-bool) mocks to Anvil via
    Foundry. Return {router, usdc, usdt} (checksummed), read from the broadcast
    artifact Foundry writes with --broadcast."""
    env = {
        **os.environ,
        "OWNER": ANVIL_ACCOUNTS["deployer"]["address"],
        "FEE_COLLECTOR": ANVIL_ACCOUNTS["feeCollector"]["address"],
        "PAYER": ANVIL_ACCOUNTS["payer"]["address"],
    }
    try:
        subprocess.run(
            [
                "forge", "script", "script/E2EDeploy.s.sol:E2EDeploy",
                "--rpc-url", anvil, "--broadcast",
                "--private-key", ANVIL_ACCOUNTS["deployer"]["key"],
            ],
            cwd=CONTRACTS_DIR, env=env, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            # Bound the deploy: a wedged forge/anvil here is the one unbounded
            # wait left in the harness and would otherwise hang the whole job.
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "E2EDeploy forge script timed out after 180s — anvil/forge wedged"
        ) from exc
    artifact = (
        CONTRACTS_DIR / "broadcast" / "E2EDeploy.s.sol" / str(CHAIN_ID) / "run-latest.json"
    )
    data = json.loads(artifact.read_text())
    addrs = {}
    for tx in data["transactions"]:
        if tx.get("transactionType") == "CREATE":
            addrs[tx["contractName"]] = Web3.to_checksum_address(tx["contractAddress"])
    return {
        "router": addrs["RSendsRouter"],
        "usdc": addrs["MockUSDC6"],
        "usdt": addrs["MockUSDT6"],
    }


class _Receiver(BaseHTTPRequestHandler):
    captured: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        type(self).captured.append({"headers": dict(self.headers), "body": body})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def webhook_receiver():
    """Local HTTP server recording every delivered webhook POST (headers + raw body)."""
    captured: list = []

    handler = type("Handler", (_Receiver,), {"captured": captured})
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield {"url": f"http://127.0.0.1:{port}/webhook", "captured": captured}
    finally:
        server.shutdown()
        server.server_close()
