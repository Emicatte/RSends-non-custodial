#!/usr/bin/env bash
# verify-autosplit-sepolia.sh — end-to-end exercise of RSendsAutoSplit on Base
# Sepolia with real USDC, the way the future keeper will drive it.
#
# The operator runs this by hand. Every state change is a `cast send` signed with
# a Foundry keystore (same convention as DeploySplitRouter — NO private key in
# env/CLI; expect one password prompt per send, up to 4 on a first full run).
# Every read is a `cast call`. Each cast invocation is echoed (`$ cast …`) before
# it runs so any single step can be copied and replayed by hand.
#
# Required env vars:
#   BASE_SEPOLIA_RPC_URL   Base Sepolia RPC endpoint
#   AUTO_SPLIT_ADDRESS     deployed RSendsAutoSplit address
#   MERCHANT_KEYSTORE      path to the merchant's Foundry keystore file
#   MERCHANT_ADDRESS       the throwaway receiving wallet (must match keystore)
#   RECIPIENT_A/B/C        arbitrary recipient addresses (need not be controlled)
# Optional:
#   MIN_AMOUNT             policy minAmount in USDC base units (default 100000
#                          = 0.10 USDC). The below-minAmount negative case needs
#                          a real floor, so keep it small but fundable.
#
# USDC's address is read from the shared token registry
# (services/backend/app/token_registry.json, chain "84532") — never hardcoded.
#
# Modes:
#   (no flag)   full flow: preflight, setPolicy, approve MAX, preview,
#               executeSplit, negative cases (incl. the real approve(0)
#               revocation path).
#   --dry-run   phases 0+3 only, zero sends. This is the reference
#               implementation of the keeper's eth_call preflight: decide
#               locally from (policy, allowance, balance) whether a split would
#               fire, then assert previewSplit agrees.
#   --self-check  no network, no sends: encode known-good fixtures with the
#               local cast and run them through this script's own parsers.
#               Run this first on any new machine/foundry version — the parsing
#               bug it guards against was a cast pretty-printer format drift.
#
# Idempotent: a policy or MAX allowance that is already in place is detected and
# skipped, not re-sent. Safe to re-run; a re-run needs the merchant funded with
# at least MIN_AMOUNT USDC again.

set -euo pipefail

# ── output helpers ──────────────────────────────────────────────────────────

pass() { printf 'PASS: %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
info() { printf '  -- %s\n' "$*"; }

# Echo the exact command to stderr, then run it (stdout stays capturable).
run() { printf '  $ %s\n' "$*" >&2; "$@"; }

# Assert that a read-only call reverts. Nothing is spent, nothing changes state.
expect_revert() {
  local label=$1; shift
  local out
  printf '  $ %s\n' "$*" >&2
  if out=$("$@" 2>&1); then
    fail "$label — call unexpectedly SUCCEEDED (returned: ${out})"
  else
    pass "$label — reverted as expected"
  fi
}

# First whitespace-separated field of stdin, validated as a decimal number
# (strips cast's "123456 [1.234e5]" annotation). FAILs printing the raw input
# so a format drift is diagnosable without a live round trip.
num_checked() { # $1 = label; stdin = raw cast output
  local raw parsed
  raw=$(cat)
  parsed=$(awk '{print $1; exit}' <<<"$raw")
  case "$parsed" in
    ''|*[!0-9]*) fail "$1 — unparseable numeric (raw: [$raw], parsed: [$parsed])" ;;
  esac
  printf '%s\n' "$parsed"
}

# Decode raw ABI return data with python3. Multi-value reads deliberately do
# NOT use cast's decoded pretty-printer: its output format drifts across
# versions (a live run parsed empty where this machine parsed fine), while raw
# hex from an annotation-free `cast call` is stable everywhere.
# Shapes:
#   policy  -> line1 recipients (lowercase, space-joined; empty line if none),
#              line2 bps (space-joined), line3 minAmount
#   preview -> line1 total, line2 amounts (space-joined)
abi_decode() { # $1 = shape, $2 = 0x-hex return data
  python3 - "$1" "$2" <<'PY'
import sys
shape, hexdata = sys.argv[1], sys.argv[2].strip()
if not hexdata.startswith("0x"):
    sys.exit(f"abi_decode: expected 0x-prefixed hex, got: {hexdata[:120]!r}")
try:
    data = bytes.fromhex(hexdata[2:])
except ValueError:
    sys.exit(f"abi_decode: invalid hex: {hexdata[:120]!r}")

def word(i):
    chunk = data[i * 32:(i + 1) * 32]
    if len(chunk) != 32:
        sys.exit(f"abi_decode: truncated data at word {i} (total {len(data)} bytes, raw: {hexdata[:120]!r})")
    return int.from_bytes(chunk, "big")

def uint_array(byte_off):
    base = byte_off // 32
    n = word(base)
    return [word(base + 1 + i) for i in range(n)]

if shape == "policy":  # (address[], uint16[], uint256)
    addrs = ["0x%040x" % v for v in uint_array(word(0))]
    bps = uint_array(word(1))
    print(" ".join(addrs))
    print(" ".join(str(b) for b in bps))
    print(word(2))
elif shape == "preview":  # (uint256, uint256[])
    print(word(0))
    print(" ".join(str(v) for v in uint_array(word(1))))
else:
    sys.exit(f"abi_decode: unknown shape {shape!r}")
PY
}

# ── inputs ──────────────────────────────────────────────────────────────────

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then DRY_RUN=1; fi

# ── --self-check: parser fixtures, no network, no env vars, no sends ────────
# Encodes known-good values with the LOCAL cast and asserts this script's own
# parsers reproduce them. Run on any new machine/foundry version first.
if [ "${1:-}" = "--self-check" ]; then
  echo "== self-check: parser fixtures (no network, no sends) =="
  command -v cast >/dev/null    || fail "cast (Foundry) not found in PATH"
  command -v python3 >/dev/null || fail "python3 not found in PATH"

  # the policy actually registered on Base Sepolia (mixed-case on purpose:
  # proves the decode is case-normalized)
  fx_a=0x316B07c37F586dBcd7adE8646c64D3df4A990f06
  fx_b=0xC52897aA5F24D00d23B57eb61124F82D44Ae1eAE
  fx_c=0x66bd2aB5F7182bAE71182A0371B1c893D099070F

  enc=$(run cast abi-encode "r(address[],uint16[],uint256)" \
    "[$fx_a,$fx_b,$fx_c]" "[3333,3333,3334]" 100000)
  decoded=$(abi_decode policy "$enc")
  got=$(sed -n '1p' <<<"$decoded")
  want="0x316b07c37f586dbcd7ade8646c64d3df4a990f06 0xc52897aa5f24d00d23b57eb61124f82d44ae1eae 0x66bd2ab5f7182bae71182a0371b1c893d099070f"
  [ "$got" = "$want" ] || fail "policy recipients decode (got: [$got], raw: $enc)"
  [ "$(sed -n '2p' <<<"$decoded")" = "3333 3333 3334" ] \
    || fail "policy bps decode (got: [$(sed -n '2p' <<<"$decoded")], raw: $enc)"
  [ "$(sed -n '3p' <<<"$decoded")" = "100000" ] \
    || fail "policy minAmount decode (got: [$(sed -n '3p' <<<"$decoded")], raw: $enc)"
  pass "policy decode matches the known-good fixture (lowercased)"

  enc=$(run cast abi-encode "r(address[],uint16[],uint256)" "[]" "[]" 0)
  decoded=$(abi_decode policy "$enc")
  [ -z "$(sed -n '1p' <<<"$decoded")" ] \
    || fail "empty policy should decode to an empty recipients line (raw: $enc)"
  pass "empty policy decodes to empty recipients (NoPolicy path intact)"

  enc=$(run cast abi-encode "r(uint256,uint256[])" 101 "[50,30,21]")
  decoded=$(abi_decode preview "$enc")
  [ "$(sed -n '1p' <<<"$decoded")" = "101" ] \
    || fail "preview total decode (got: [$(sed -n '1p' <<<"$decoded")], raw: $enc)"
  [ "$(sed -n '2p' <<<"$decoded")" = "50 30 21" ] \
    || fail "preview amounts decode (got: [$(sed -n '2p' <<<"$decoded")], raw: $enc)"
  pass "preview decode matches fixture"

  parsed=$(printf '100000 [1e5]\n' | num_checked "scalar fixture")
  [ "$parsed" = "100000" ] || fail "scalar parse (got: [$parsed])"
  pass "scalar parse strips the [1e5]-style annotation"

  echo "== self-check complete: all parsers OK =="
  exit 0
fi

for var in BASE_SEPOLIA_RPC_URL AUTO_SPLIT_ADDRESS MERCHANT_KEYSTORE \
           MERCHANT_ADDRESS RECIPIENT_A RECIPIENT_B RECIPIENT_C; do
  [ -n "${!var:-}" ] || fail "required env var $var is not set"
done
[ -f "$MERCHANT_KEYSTORE" ] || fail "MERCHANT_KEYSTORE is not a file: $MERCHANT_KEYSTORE"

MIN_AMOUNT="${MIN_AMOUNT:-100000}" # 0.10 USDC in base units

command -v cast >/dev/null    || fail "cast (Foundry) not found in PATH"
command -v python3 >/dev/null || fail "python3 not found in PATH"

RPC=(--rpc-url "$BASE_SEPOLIA_RPC_URL")
SIGN=(--keystore "$MERCHANT_KEYSTORE")
BPS_A=3333; BPS_B=3333; BPS_C=3334

# USDC address comes from the shared registry — the single source of truth the
# backend and SetFeeConfig.s.sol already read. Never invented, never modified.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="$SCRIPT_DIR/../../../services/backend/app/token_registry.json"
[ -f "$REGISTRY" ] || fail "token registry not found at $REGISTRY"
USDC_ADDRESS=$(python3 - "$REGISTRY" <<'PY'
import json, sys
reg = json.load(open(sys.argv[1]))
tok = reg.get("84532", {}).get("tokens", {}).get("USDC")
print(tok["address"] if tok and tok.get("address") else "")
PY
)
[ -n "$USDC_ADDRESS" ] || fail \
  "no USDC entry under chain \"84532\" in $REGISTRY — add it there (registry is the source of truth; this script will not invent an address)"
info "USDC (from registry): $USDC_ADDRESS"
info "minAmount: $MIN_AMOUNT base units"

usdc_balance() {
  run cast call "$USDC_ADDRESS" "balanceOf(address)(uint256)" "$1" "${RPC[@]}" \
    | num_checked "USDC balanceOf($1)"
}

# ── phase 0: preflight (read-only) ──────────────────────────────────────────

echo "== phase 0: preflight =="

chain_id=$(run cast chain-id "${RPC[@]}") || fail "RPC unreachable: $BASE_SEPOLIA_RPC_URL"
[ "$chain_id" = "84532" ] || fail "chainId is $chain_id, expected 84532 (Base Sepolia)"
pass "RPC reachable, chainId 84532"

code=$(run cast code "$AUTO_SPLIT_ADDRESS" "${RPC[@]}")
[ "$code" != "0x" ] || fail "no code at AUTO_SPLIT_ADDRESS $AUTO_SPLIT_ADDRESS"
pass "code present at AUTO_SPLIT_ADDRESS"

code=$(run cast code "$USDC_ADDRESS" "${RPC[@]}")
[ "$code" != "0x" ] || fail "no code at USDC address $USDC_ADDRESS"
pass "code present at USDC address"

eth_bal=$(run cast balance "$MERCHANT_ADDRESS" "${RPC[@]}" | num_checked "ETH balance")
[ "$eth_bal" != "0" ] || fail "MERCHANT_ADDRESS has no ETH for gas" # string compare: wei can exceed bash's 2^63
pass "merchant has ETH for gas ($eth_bal wei)"

merchant_usdc=$(usdc_balance "$MERCHANT_ADDRESS")
info "merchant USDC balance: $merchant_usdc base units"
if [ "$DRY_RUN" -eq 0 ]; then
  if [ "$merchant_usdc" -eq 0 ]; then
    fail "merchant USDC balance is zero — fund $MERCHANT_ADDRESS from the Circle faucet (https://faucet.circle.com, network: Base Sepolia) and re-run"
  fi
  if [ "$merchant_usdc" -lt "$MIN_AMOUNT" ]; then
    fail "merchant USDC balance ($merchant_usdc) is below MIN_AMOUNT ($MIN_AMOUNT) — executeSplit would revert BelowMinAmount; top up via the Circle faucet (https://faucet.circle.com, network: Base Sepolia)"
  fi
  pass "merchant USDC balance covers minAmount"
fi

# ── shared reads: policy / allowance ────────────────────────────────────────

# Annotation-free call -> raw ABI hex -> python decode. policy_raw is kept for
# diagnostics: every FAIL involving these values prints it.
read_policy() { # sets policy_raw, policy_recipients, policy_bps, policy_min
  local decoded
  policy_raw=$(run cast call "$AUTO_SPLIT_ADDRESS" "getPolicy(address,address)" \
    "$MERCHANT_ADDRESS" "$USDC_ADDRESS" "${RPC[@]}")
  decoded=$(abi_decode policy "$policy_raw")
  policy_recipients=$(sed -n '1p' <<<"$decoded")
  policy_bps=$(sed -n '2p' <<<"$decoded")
  policy_min=$(sed -n '3p' <<<"$decoded")
}

read_allowance() {
  run cast call "$USDC_ADDRESS" "allowance(address,address)(uint256)" \
    "$MERCHANT_ADDRESS" "$AUTO_SPLIT_ADDRESS" "${RPC[@]}" | num_checked "allowance"
}

# Expected distribution under the RSendsAutoSplit convention: floor per leg,
# remainder to the LAST leg (that is what closes the wallet to exactly zero).
# Bash 64-bit arithmetic is fine: testnet USDC amounts * 10000 are far below 2^63.
compute_expected() { # $1 = total; uses BPS_A/B/C; sets exp_a, exp_b, exp_c, dust
  local total=$1
  exp_a=$(( total * BPS_A / 10000 ))
  exp_b=$(( total * BPS_B / 10000 ))
  exp_c=$(( total - exp_a - exp_b ))
  dust=$(( exp_c - total * BPS_C / 10000 ))
}

# ── phase 3 body (shared with --dry-run): preview vs local expectation ──────

check_preview() {
  local total=$1
  compute_expected "$total"
  info "distributable amount: $total | legs: A=$exp_a B=$exp_b C=$exp_c | dust(->last): $dust"

  local raw decoded preview_total preview_amounts
  raw=$(run cast call "$AUTO_SPLIT_ADDRESS" "previewSplit(address,address)" \
    "$MERCHANT_ADDRESS" "$USDC_ADDRESS" "${RPC[@]}")
  decoded=$(abi_decode preview "$raw")
  preview_total=$(sed -n '1p' <<<"$decoded")
  preview_amounts=$(sed -n '2p' <<<"$decoded")

  [ "$preview_total" = "$total" ] \
    || fail "previewSplit total $preview_total != expected $total (raw: $raw)"
  [ "$preview_amounts" = "$exp_a $exp_b $exp_c" ] \
    || fail "previewSplit amounts [$preview_amounts] != expected [$exp_a $exp_b $exp_c] (raw: $raw)"
  pass "previewSplit matches the locally computed distribution exactly"
}

# ── --dry-run: the keeper's eth_call preflight, and nothing else ────────────

if [ "$DRY_RUN" -eq 1 ]; then
  echo "== dry run: keeper preflight (no sends) =="
  read_policy
  allowance=$(read_allowance)
  info "allowance: $allowance"

  # Decide locally, exactly like the keeper will, then assert the contract agrees.
  skip_reason=""
  if [ -z "$policy_recipients" ]; then
    skip_reason="no policy registered (NoPolicy)"
  else
    # min() via python3: a MAX allowance (2^256-1) overflows bash's 64-bit arithmetic.
    total=$(python3 -c "print(min(int('$merchant_usdc'), int('$allowance')))")
    if [ "$total" -eq 0 ]; then
      skip_reason="nothing distributable: min(balance=$merchant_usdc, allowance=$allowance) = 0 (ZeroAmount)"
    elif [ "$total" -lt "$policy_min" ]; then
      skip_reason="distributable $total < minAmount $policy_min (BelowMinAmount)"
    fi
  fi

  if [ -n "$skip_reason" ]; then
    info "keeper would SKIP: $skip_reason"
    expect_revert "previewSplit agrees with the local skip decision" \
      cast call "$AUTO_SPLIT_ADDRESS" "previewSplit(address,address)" \
      "$MERCHANT_ADDRESS" "$USDC_ADDRESS" "${RPC[@]}"
    echo "== dry run complete: keeper would skip =="
    exit 0
  fi

  check_preview "$total"
  echo "== dry run complete: keeper would execute =="
  exit 0
fi

# ── phase 1: setPolicy (idempotent) ─────────────────────────────────────────

echo "== phase 1: setPolicy =="

want_recipients=$(tr '[:upper:]' '[:lower:]' <<<"$RECIPIENT_A $RECIPIENT_B $RECIPIENT_C")
read_policy
if [ "$policy_recipients" = "$want_recipients" ] \
   && [ "$policy_bps" = "$BPS_A $BPS_B $BPS_C" ] \
   && [ "$policy_min" = "$MIN_AMOUNT" ]; then
  pass "policy already set as expected — skipping setPolicy"
else
  run cast send "$AUTO_SPLIT_ADDRESS" \
    "setPolicy(address,address[],uint16[],uint256)" \
    "$USDC_ADDRESS" "[$RECIPIENT_A,$RECIPIENT_B,$RECIPIENT_C]" \
    "[$BPS_A,$BPS_B,$BPS_C]" "$MIN_AMOUNT" \
    "${SIGN[@]}" "${RPC[@]}"
  read_policy
  [ "$policy_recipients" = "$want_recipients" ] \
    || fail "getPolicy recipients [$policy_recipients] != [$want_recipients] (raw: $policy_raw)"
  [ "$policy_bps" = "$BPS_A $BPS_B $BPS_C" ] \
    || fail "getPolicy bps [$policy_bps] != [$BPS_A $BPS_B $BPS_C] (raw: $policy_raw)"
  [ "$policy_min" = "$MIN_AMOUNT" ] \
    || fail "getPolicy minAmount $policy_min != $MIN_AMOUNT (raw: $policy_raw)"
  pass "policy stored and read back correctly"
fi

# ── phase 2: approve MAX (idempotent) ───────────────────────────────────────

echo "== phase 2: approve =="

MAX_UINT=$(cast max-uint | num_checked "cast max-uint") # awk-stripped: defensive vs suffix drift
allowance=$(read_allowance)
if [ "$allowance" = "$MAX_UINT" ]; then
  pass "allowance already MAX — skipping approve"
else
  run cast send "$USDC_ADDRESS" "approve(address,uint256)" \
    "$AUTO_SPLIT_ADDRESS" "$MAX_UINT" "${SIGN[@]}" "${RPC[@]}"
  allowance=$(read_allowance)
  [ "$allowance" = "$MAX_UINT" ] || fail "allowance is $allowance, expected MAX"
  pass "allowance is MAX"
fi

# ── phase 3: preview vs locally computed expectation ────────────────────────

echo "== phase 3: previewSplit =="

merchant_usdc=$(usdc_balance "$MERCHANT_ADDRESS") # re-read: live number, no staleness
check_preview "$merchant_usdc"

# ── phase 4: executeSplit ───────────────────────────────────────────────────

echo "== phase 4: executeSplit =="

pre_merchant=$merchant_usdc
pre_a=$(usdc_balance "$RECIPIENT_A")
pre_b=$(usdc_balance "$RECIPIENT_B")
pre_c=$(usdc_balance "$RECIPIENT_C")

run cast send "$AUTO_SPLIT_ADDRESS" "executeSplit(address,address)" \
  "$MERCHANT_ADDRESS" "$USDC_ADDRESS" "${SIGN[@]}" "${RPC[@]}"

post_merchant=$(usdc_balance "$MERCHANT_ADDRESS")
post_a=$(usdc_balance "$RECIPIENT_A")
post_b=$(usdc_balance "$RECIPIENT_B")
post_c=$(usdc_balance "$RECIPIENT_C")

[ "$post_merchant" -eq 0 ] || fail "merchant balance is $post_merchant, expected exactly 0"
pass "merchant balance is exactly 0"

compute_expected "$pre_merchant"
[ $(( post_a - pre_a )) -eq "$exp_a" ] || fail "recipient A delta $(( post_a - pre_a )) != $exp_a"
[ $(( post_b - pre_b )) -eq "$exp_b" ] || fail "recipient B delta $(( post_b - pre_b )) != $exp_b"
[ $(( post_c - pre_c )) -eq "$exp_c" ] || fail "recipient C delta $(( post_c - pre_c )) != $exp_c"
pass "each recipient increased by exactly its expected leg"

delta_sum=$(( (post_a - pre_a) + (post_b - pre_b) + (post_c - pre_c) ))
[ "$delta_sum" -eq "$pre_merchant" ] \
  || fail "sum of recipient deltas $delta_sum != pre-execution balance $pre_merchant"
pass "conservation: recipient deltas sum to the full pre-execution balance"

# ── phase 5: negative cases ─────────────────────────────────────────────────

echo "== phase 5: negative cases =="

# 5a. Immediate re-execution: wallet just drained to zero.
expect_revert "second consecutive executeSplit (zero balance)" \
  cast call "$AUTO_SPLIT_ADDRESS" "executeSplit(address,address)" \
  "$MERCHANT_ADDRESS" "$USDC_ADDRESS" "${RPC[@]}"

# 5b. Below-minAmount: needs a real sub-threshold balance, so the operator funds it.
echo ""
echo "  ACTION REQUIRED: send LESS than $MIN_AMOUNT USDC base units"
echo "  (e.g. $(( MIN_AMOUNT / 2 ))) to $MERCHANT_ADDRESS, then press Enter."
read -r -p "  Waiting for you to fund... " _
while :; do
  bal=$(usdc_balance "$MERCHANT_ADDRESS")
  [ "$bal" -gt 0 ] && break
  info "balance still 0 — waiting 5s (Ctrl-C to abort)"
  sleep 5
done
[ "$bal" -lt "$MIN_AMOUNT" ] \
  || fail "you funded $bal >= MIN_AMOUNT $MIN_AMOUNT — the below-minAmount case cannot run; re-run the script to distribute this balance, then fund a smaller amount"
info "merchant funded with $bal (< minAmount $MIN_AMOUNT)"
expect_revert "executeSplit below minAmount" \
  cast call "$AUTO_SPLIT_ADDRESS" "executeSplit(address,address)" \
  "$MERCHANT_ADDRESS" "$USDC_ADDRESS" "${RPC[@]}"

# 5c. Revocation — exercised FOR REAL: approve(0) is the merchant's kill switch.
run cast send "$USDC_ADDRESS" "approve(address,uint256)" \
  "$AUTO_SPLIT_ADDRESS" 0 "${SIGN[@]}" "${RPC[@]}"
allowance=$(read_allowance)
[ "$allowance" = "0" ] || fail "allowance is $allowance after approve(0), expected 0"
pass "allowance revoked to 0"
expect_revert "executeSplit after approve(0)" \
  cast call "$AUTO_SPLIT_ADDRESS" "executeSplit(address,address)" \
  "$MERCHANT_ADDRESS" "$USDC_ADDRESS" "${RPC[@]}"

echo ""
echo "== all phases complete =="
info "note: the merchant wallet still holds $bal base units with allowance 0;"
info "re-approve and re-run to distribute it, or leave it as test dust."
