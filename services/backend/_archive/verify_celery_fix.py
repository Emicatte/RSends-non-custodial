"""
Verify Celery .delay() fix — S4 regression test.

Sends 10 webhooks sequentially to the backend (without Redis).
All 10 must return 200 OK in <500ms each.

Previous behavior: ~19,100ms per webhook (Celery retry loop blocking event loop)
Expected after fix: <500ms per webhook (immediate fallback to async processing)
"""

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import aiohttp

BACKEND_URL = "http://127.0.0.1:8000/api/v1/webhooks/alchemy"
WEBHOOK_SECRET = "test-secret-for-qa"
NUM_WEBHOOKS = 10

SOURCE_WALLETS = [
    "0xa61a471fc226a06c68902ea46c252498a9460c26",
    "0xba304810a4b69bda0058fb9606da0a28a7d07c28",
    "0x6496189b56802e390924610dbab0a8db6a47c938",
    "0x627830dae5035fe11816383f2b4bffc0c6de1c26",
    "0x2ae5fbf5bdec151fa0e35b8200f0d3b4b6eb2c30",
]


def build_webhook_payload(idx: int) -> dict:
    wallet = SOURCE_WALLETS[idx % len(SOURCE_WALLETS)]
    return {
        "webhookId": f"wh_verify_{idx:04d}",
        "id": f"wh_verify_{idx:04d}",
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "ADDRESS_ACTIVITY",
        "event": {
            "network": "BASE_SEPOLIA",
            "activity": [
                {
                    "fromAddress": f"0x{'a' * 38}{idx:02d}",
                    "toAddress": wallet,
                    "value": 0.001,
                    "asset": "ETH",
                    "hash": f"0x{'b' * 62}{idx:02d}",
                    "blockNum": 39780000 + idx,
                    "category": "external",
                }
            ],
        },
    }


def sign_payload(body: bytes) -> str:
    return hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()


async def main():
    print(f"{'='*60}")
    print(f"  Celery .delay() Fix Verification")
    print(f"  Sending {NUM_WEBHOOKS} webhooks (no Redis)")
    print(f"{'='*60}\n")

    results = []
    async with aiohttp.ClientSession() as session:
        for i in range(NUM_WEBHOOKS):
            payload = build_webhook_payload(i)
            body = json.dumps(payload).encode()
            sig = sign_payload(body)

            headers = {
                "Content-Type": "application/json",
                "X-Alchemy-Signature": sig,
                "X-Forwarded-For": f"10.10.{i // 256}.{i % 256 + 1}",
                "X-Real-IP": f"10.10.{i // 256}.{i % 256 + 1}",
            }

            t0 = time.monotonic()
            try:
                async with session.post(
                    BACKEND_URL, data=body, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    status = resp.status
                    text = await resp.text()
                    latency_ms = (time.monotonic() - t0) * 1000
            except Exception as e:
                status = 0
                text = str(e)
                latency_ms = (time.monotonic() - t0) * 1000

            passed = status == 200 and latency_ms < 500
            mark = "PASS" if passed else "FAIL"
            results.append((i + 1, status, latency_ms, mark, text[:80]))
            print(f"  #{i+1:2d}  {status}  {latency_ms:8.1f}ms  [{mark}]  {text[:60]}")

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")

    total_pass = sum(1 for r in results if r[3] == "PASS")
    total_fail = NUM_WEBHOOKS - total_pass
    latencies = [r[2] for r in results if r[1] == 200]

    print(f"  Passed:    {total_pass}/{NUM_WEBHOOKS}")
    print(f"  Failed:    {total_fail}/{NUM_WEBHOOKS}")
    if latencies:
        print(f"  Latency p50: {sorted(latencies)[len(latencies)//2]:.1f}ms")
        print(f"  Latency max: {max(latencies):.1f}ms")
        print(f"  Latency avg: {sum(latencies)/len(latencies):.1f}ms")
    print()

    if total_pass == NUM_WEBHOOKS:
        print("  VERDICT: PASS — All webhooks <500ms without Redis")
        print(f"           (was ~19,100ms before fix)")
    else:
        print(f"  VERDICT: FAIL — {total_fail} webhooks exceeded 500ms or returned non-200")

    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
