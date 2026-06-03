#!/usr/bin/env bash
# M1-B — configura i firmatari multisig su un FeeRouterV6/V5 deployato.
#
# Usage:
#   V6_ADDR=0x...  SIGNERS="0xaaa...,0xbbb...,0xccc..."  THRESHOLD=2  \
#   RPC_URL=https://...  OWNER_KEY=0x...  ./ops/set-oracle-signers-v6.sh
#
# ⚠️  SIGNERS deve essere in ordine ASCENDING per indirizzo, SENZA duplicati,
#     max 10. THRESHOLD: 1 <= THRESHOLD <= numero signer.
# Richiede `cast` (Foundry) nel PATH.
set -euo pipefail
: "${V6_ADDR:?serve V6_ADDR}"
: "${SIGNERS:?serve SIGNERS (CSV ascending)}"
: "${THRESHOLD:?serve THRESHOLD}"
: "${RPC_URL:?serve RPC_URL}"
: "${OWNER_KEY:?serve OWNER_KEY}"

cast send "$V6_ADDR" "setOracleSigners(address[],uint8)" "[$SIGNERS]" "$THRESHOLD" \
  --rpc-url "$RPC_URL" --private-key "$OWNER_KEY"

echo "[verify] signers   = $(cast call "$V6_ADDR" 'getOracleSigners()(address[])' --rpc-url "$RPC_URL")"
echo "[verify] threshold = $(cast call "$V6_ADDR" 'oracleThreshold()(uint8)' --rpc-url "$RPC_URL")"
echo "[verify] domainSep = $(cast call "$V6_ADDR" 'domainSeparator()(bytes32)' --rpc-url "$RPC_URL")"
