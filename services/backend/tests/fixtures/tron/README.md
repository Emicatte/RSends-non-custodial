# Recorded TRON Nile responses

These are what the chain actually said, recorded from `https://nile.trongrid.io` on 2026-09-03.
They are not hand-written, and they must not be edited by hand: a fixture that has been "tidied"
stops being evidence of anything. Mutate copies inside a test when a test needs a mutation — several
do, and they say so.

This is the first fixture directory in the backend suite, which otherwise builds request/response
shapes as inline dicts. That style is right for a shape someone reasoned about; it is wrong here.
The whole point of `tron_verifier` is that it agrees with a real node about a real transfer, and an
inline dict would only prove it agrees with my idea of one.

## What is here

One directory per transaction id, each containing the three responses the verifier and the poller
read:

- `gettransactioninfobyid.json` — `POST /walletsolidity/gettransactioninfobyid`, the solidified
  receipt. Present only once the transaction has solidified; `{}` until then, and `{}` forever for a
  hash that does not exist. Those two are indistinguishable, which is why both are Pending.
- `gettransactionbyid.json` — `POST /walletsolidity/gettransactionbyid`, for `ret[0].contractRet`.
- `events.json` — `GET /v1/transactions/{txid}/events`, the only source of `event_index`.

| transaction | what it is |
|---|---|
| `07f1b19d…` | 2.5 USDT to `TAGfrptqq5mAK8EqJcXJeaTxf4zNYnUBpL`, SUCCESS |
| `e43d5619…` | 2.5 USDT to the same address, SUCCESS |
| `75e4fda0…` | 3.0 USDT to the same address, SUCCESS |
| `b58adf31…` | 1.5 USDT **out** of that address to `TNHUQgX2…` — a real wrong-recipient case, no mutation needed |
| `254814d8…` | a plain TRX `TransferContract`: no `log`, no `receipt.result`, only `net_usage`. A successful transaction that is not a TRC-20 transfer at all |

Plus `discovery_trc20_TAGfrptqq5mAK8EqJcXJeaTxf4zNYnUBpL.json`, the
`GET /v1/accounts/{addr}/transactions/trc20` response the **poller** works from. It exists so the
index-provenance test can compare the verifier's `log_index` against what the poller's own enrichment
derives for the same transaction, from a genuinely different starting point.

## Not here: a deliberately failed transfer

Recording one means signing and broadcasting from the faucet account. There is no private key in this
repository and nothing here signs or spends, so it was not done. `reverted` and `out_of_energy` are
reached by mutating a recorded `receipt.result` in the test, which is the same method the other
rejection cases use. If a real failed transaction is wanted, add its txid and re-record.

## Re-recording

```sh
TX=07f1b19de88dec6213e95b96715bfa3198b1ab38d7228810d46c3a2e25ff91d3
N=https://nile.trongrid.io
curl -s -X POST $N/walletsolidity/gettransactioninfobyid -H 'content-type: application/json' \
  -d "{\"value\":\"$TX\"}" | python3 -m json.tool
curl -s $N/v1/transactions/$TX/events | python3 -m json.tool
```

Nile is a testnet and its history is not guaranteed forever. If these transactions are ever pruned
the fixtures still stand on their own — that is the point of committing them — but they can no longer
be re-recorded from the same hashes. **No test here touches the network.**
