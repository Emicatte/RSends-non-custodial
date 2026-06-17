#!/bin/bash
set -e

if [ -z "$PRIVATE_KEY" ]; then
  echo "ERROR: export PRIVATE_KEY=... first"
  exit 1
fi

cd "$(dirname "$0")"

declare -A RPC NAME TOKENS

RPC[42161]="https://arb1.arbitrum.io/rpc"         ; NAME[42161]="Arbitrum"
RPC[10]="https://mainnet.optimism.io"              ; NAME[10]="Optimism"
RPC[137]="https://polygon-rpc.com"                 ; NAME[137]="Polygon"
RPC[43114]="https://api.avax.network/ext/bc/C/rpc" ; NAME[43114]="Avalanche"
RPC[56]="https://bsc-dataseed.binance.org"         ; NAME[56]="BNB"
RPC[1]="https://eth.llamarpc.com"                  ; NAME[1]="Ethereum"

TOKENS[1]="[0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48,0xdAC17F958D2ee523a2206206994597C13D831ec7,0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2,0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599,0x1aBaEA1f7C830bD89Acc67eC4af516284b1bC33c]"
TOKENS[10]="[0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85,0x94b008aA00579c1307B0EF2c499aD98a8ce58e58,0x4200000000000000000000000000000000000006]"
TOKENS[42161]="[0xaf88d065e77c8cC2239327C5EDb3A432268e5831,0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9,0x82aF49447D8a07e3bd95BD0d56f35241523fBab1,0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f]"
TOKENS[137]="[0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359,0xc2132D05D31c914a87C6611C10748AEb04B58e8F,0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270,0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6]"
TOKENS[56]="[0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d,0x55d398326f99059fF775485246999027B3197955,0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c]"
TOKENS[43114]="[0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E,0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7,0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7]"

echo "═══════════════════════════════════════"
echo "  FeeRouterV4 Multi-Chain Deploy"
echo "═══════════════════════════════════════"

RESULTS=""

for CHAIN_ID in 42161 10 137 43114 56 1; do
  CHAIN_RPC="${RPC[$CHAIN_ID]}"
  CHAIN_NAME="${NAME[$CHAIN_ID]}"
  CHAIN_TOKENS="${TOKENS[$CHAIN_ID]}"

  echo ""
  echo "──── $CHAIN_NAME (chain $CHAIN_ID) ────"

  # Deploy
  echo "Deploying..."
  OUTPUT=$(forge script script/DeployAllChains.s.sol:DeployAllChains \
    --rpc-url "$CHAIN_RPC" \
    --broadcast \
    --slow \
    -vvv 2>&1) || true

  ADDR=$(echo "$OUTPUT" | grep "Address:" | tail -1 | awk '{print $NF}')

  if [ -z "$ADDR" ]; then
    echo "❌ Deploy FAILED"
    echo "$OUTPUT" | tail -10
    RESULTS="$RESULTS\n❌ $CHAIN_NAME ($CHAIN_ID): FAILED"
    continue
  fi

  echo "✅ Deployed: $ADDR"

  # Enable tokens
  echo "Enabling tokens..."
  NUM_TOKENS=$(echo "$CHAIN_TOKENS" | tr ',' '\n' | wc -l | tr -d ' ')
  BOOLS=$(printf ',true%.0s' $(seq 1 $NUM_TOKENS))
  BOOLS="[${BOOLS:1}]"

  cast send "$ADDR" \
    "setTokensAllowed(address[],bool[])" \
    "$CHAIN_TOKENS" "$BOOLS" \
    --rpc-url "$CHAIN_RPC" \
    --private-key "$PRIVATE_KEY" 2>/dev/null && echo "✅ Tokens enabled" || echo "⚠️ Token setup failed"

  # Verify
  echo "Verifying..."
  SIGNER=$(cast call "$ADDR" "oracleSigner()" --rpc-url "$CHAIN_RPC" 2>/dev/null)
  FEE=$(cast call "$ADDR" "feeBps()" --rpc-url "$CHAIN_RPC" 2>/dev/null)
  echo "  OracleSigner: $SIGNER"
  echo "  feeBps: $FEE"

  RESULTS="$RESULTS\n✅ $CHAIN_NAME ($CHAIN_ID): $ADDR"
  echo "──── $CHAIN_NAME done ────"
done

echo ""
echo "═══════════════════════════════════════"
echo "  RESULTS"
echo -e "$RESULTS"
echo ""
echo "NEXT: Copia indirizzi in .env.local + contractRegistry.ts"
echo "      poi: rm -rf .next && npm run dev"
