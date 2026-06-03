#!/usr/bin/env bash
# Smoke-test post-deploy (sez. 7 del GO_LIVE_RUNBOOK): verifica che i fix di
# sicurezza siano ATTIVI in prod. Read-only (nessuna mutazione).
#
# Usage:
#   DOMAIN=https://app.example.com  BACKEND=https://backend.example.com  \
#   HMAC_SECRET=<...>  ./ops/smoke-test.sh
#   (se BACKEND non è dato, usa DOMAIN)
set -euo pipefail
: "${DOMAIN:?serve DOMAIN (host del frontend Next)}"
: "${HMAC_SECRET:?serve HMAC_SECRET (= X-Admin-Token)}"
BACKEND="${BACKEND:-$DOMAIN}"

code()  { curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$@"; }
check() { # $1=ottenuto $2=atteso $3=descrizione
  if [ "$1" = "$2" ]; then echo "  ✅ $3 ($1)"; else echo "  ❌ $3 (atteso $2, ottenuto $1)"; fi
}

echo "== Backend (deny-by-default / admin gating) =="
check "$(code "$BACKEND/api/v1/ledger/accounts")" "401" "M8/H1 ledger anonimo negato"
check "$(code "$BACKEND/health/config")" "403" "M7 /health/config senza token"
check "$(code -H "X-Admin-Token: $HMAC_SECRET" "$BACKEND/health/config")" "200" "M7 /health/config con token"
check "$(code "$BACKEND/api/v1/forwarding/spending-limits?source_address=0x0000000000000000000000000000000000000001")" "401" "M9 spending-limits senza wallet-auth"

echo "== Next proxy (H3 denylist) =="
check "$(code -X POST "$DOMAIN/api/backend/api/internal/signing/audit")" "404" "H3 internal denylist dal browser"

echo "== L1 — oracle GET non espone internals in prod =="
body="$(curl -s --max-time 15 "$DOMAIN/api/oracle/sign" || true)"
if echo "$body" | grep -q "signerAddress\|envDebug\|domainSeparatorHash"; then
  echo "  ❌ L1 oracle GET espone ancora internals (setta NODE_ENV=production, togli ORACLE_DEBUG)"
else
  echo "  ✅ L1 oracle GET minimale: $(echo "$body" | head -c 80)"
fi
