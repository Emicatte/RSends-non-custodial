#!/bin/bash
set -e

# ── Config ──
# PRIVATE_KEY must be set in environment or contracts/.env
# NEVER commit the private key to the repo
if [ -z "$PRIVATE_KEY" ]; then
  if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
  fi
  if [ -z "$PRIVATE_KEY" ]; then
    echo "❌ PRIVATE_KEY not set. Export it or add to contracts/.env"
    exit 1
  fi
fi

# ── RPC URLs ──
declare -A RPC
RPC[42161]="https://arb1.arbitrum.io/rpc"
RPC[10]="https://mainnet.optimism.io"
RPC[137]="https://polygon-rpc.com"
RPC[43114]="https://api.avax.network/ext/bc/C/rpc"
RPC[56]="https://bsc-dataseed.binance.org"
RPC[1]="https://eth.llamarpc.com"

declare -A CHAIN_NAME
CHAIN_NAME[42161]="Arbitrum"
CHAIN_NAME[10]="Optimism"
CHAIN_NAME[137]="Polygon"
CHAIN_NAME[43114]="Avalanche"
CHAIN_NAME[56]="BNB Chain"
CHAIN_NAME[1]="Ethereum"

echo "═══════════════════════════════════════"
echo "  FeeRouterV4 Multi-Chain Deploy"
echo "═══════════════════════════════════════"

RESULTS=""

# Deploy order: cheapest gas first
for CHAIN_ID in 42161 10 137 43114 56 1; do
  CHAIN_RPC="${RPC[$CHAIN_ID]}"
  NAME="${CHAIN_NAME[$CHAIN_ID]}"
  echo ""
  echo "──── Deploying on $NAME ($CHAIN_ID) ────"

  # Deploy
  OUTPUT=$(forge script script/DeployMultiChain.s.sol:DeployMultiChain \
    --rpc-url "$CHAIN_RPC" \
    --broadcast \
    --verify \
    --slow \
    -vvv 2>&1) || true

  # Extract address from log
  ADDR=$(echo "$OUTPUT" | grep "FeeRouterV4 deployed at:" | awk '{print $NF}')

  if [ -z "$ADDR" ]; then
    echo "❌ Deploy FAILED on $NAME ($CHAIN_ID)"
    echo "$OUTPUT" | tail -5
    RESULTS="$RESULTS\n❌ $NAME ($CHAIN_ID): FAILED"
    continue
  fi

  echo "✅ Deployed: $ADDR"
  RESULTS="$RESULTS\n✅ $NAME ($CHAIN_ID): $ADDR"

  # Setup token allowlist
  echo "Setting up allowed tokens..."
  ROUTER_ADDRESS=$ADDR forge script script/SetupTokens.s.sol:SetupTokens \
    --rpc-url "$CHAIN_RPC" \
    --broadcast \
    --slow \
    -vvv 2>&1 || echo "⚠️  Token setup failed — run manually"

  echo "──── $NAME ($CHAIN_ID) done ────"
done

echo ""
echo "═══════════════════════════════════════"
echo "  DEPLOYMENT RESULTS"
echo "═══════════════════════════════════════"
echo -e "$RESULTS"
echo ""
echo "NEXT STEPS:"
echo "1. Copy addresses to lib/contractRegistry.ts (feeRouter fields)"
echo "2. Copy addresses to .env.local (NEXT_PUBLIC_FEE_ROUTER_V4_*)"
echo "3. Update app/api/oracle/sign/route.ts (routerForChain switch)"
echo "4. Verify contracts on explorers"
echo "5. Test a small transaction on each chain"
