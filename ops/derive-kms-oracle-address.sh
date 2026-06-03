#!/usr/bin/env bash
# Deriva l'address Ethereum della/e chiave/i KMS oracle (M1-A single / M1-B multisig).
#
# Eseguilo DOVE il backend ha le sue dipendenze + credenziali AWS (es. shell di
# Render, o un venv locale con boto3 e AWS creds), con le env KMS settate:
#   export ORACLE_SIGNER_MODE=kms
#   export AWS_REGION=<region>
#   export ORACLE_KMS_KEY_ID=<id>            # single signer (M1-A)
#   # oppure per multisig (M1-B):
#   export ORACLE_KMS_KEY_IDS=id1,id2,id3    # stampa TUTTI gli address (ordina ascending!)
#
# Stampa un address per riga. Per il multisig, ordina poi gli address in ASCENDING.
set -euo pipefail

# Usa il python del venv se presente, altrimenti quello di sistema (container).
cd "$(dirname "$0")/../rpagos-backend"
PY="python"
[ -x "./venv/bin/python" ] && PY="./venv/bin/python"

"$PY" -c "
import asyncio
from app.services.key_manager import get_oracle_signers
async def main():
    for s in get_oracle_signers():
        print(await s.get_address())
asyncio.run(main())
"
