#!/usr/bin/env bash
# M1-A — punta il FeeRouterV4 (rail vivo) all'address della chiave KMS oracle.
# NESSUN redeploy del contratto (V4 ha setOracleSigner mutabile).
#
# Usage:
#   V4_ADDR=0x...  KMS_ADDR=0x...  RPC_URL=https://...  OWNER_KEY=0x...  \
#   ./ops/set-oracle-signer-v4.sh
#
# OWNER_KEY = chiave dell'OWNER del contratto (idealmente da hardware/cold).
# Richiede `cast` (Foundry) nel PATH.
set -euo pipefail
: "${V4_ADDR:?serve V4_ADDR}"
: "${KMS_ADDR:?serve KMS_ADDR}"
: "${RPC_URL:?serve RPC_URL}"
: "${OWNER_KEY:?serve OWNER_KEY}"

echo "[prima]  oracleSigner = $(cast call "$V4_ADDR" 'oracleSigner()(address)' --rpc-url "$RPC_URL")"
cast send "$V4_ADDR" "setOracleSigner(address)" "$KMS_ADDR" \
  --rpc-url "$RPC_URL" --private-key "$OWNER_KEY"
echo "[dopo]   oracleSigner = $(cast call "$V4_ADDR" 'oracleSigner()(address)' --rpc-url "$RPC_URL")"
echo "[atteso] $KMS_ADDR"
