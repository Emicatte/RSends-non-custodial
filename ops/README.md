# ops/ — script di attivazione go-live

Helper per le **attivazioni ops** del `../GO_LIVE_RUNBOOK.md`. Nessuno script
contiene segreti: li passi tu a runtime via env var. Eseguili dove hai gli
accessi giusti (AWS creds, chiave owner, `cast`/Foundry, deps backend).

| Script | Cosa fa | Variabili |
|---|---|---|
| `gen-secrets.sh` | genera `INTERNAL_PROXY_SECRET`/`HMAC_SECRET`/`ADMIN_SECRET`/`AUTH_JWT_SECRET` | — |
| `derive-kms-oracle-address.sh` | stampa l'address Ethereum della/e chiave/i KMS oracle | `ORACLE_SIGNER_MODE=kms`, `AWS_REGION`, `ORACLE_KMS_KEY_ID` o `ORACLE_KMS_KEY_IDS` |
| `set-oracle-signer-v4.sh` | M1-A: `setOracleSigner` sul V4 vivo (no redeploy) | `V4_ADDR`, `KMS_ADDR`, `RPC_URL`, `OWNER_KEY` |
| `set-oracle-signers-v6.sh` | M1-B: `setOracleSigners(address[],uint8)` sul V6 | `V6_ADDR`, `SIGNERS` (ascending), `THRESHOLD`, `RPC_URL`, `OWNER_KEY` |
| `smoke-test.sh` | verifica post-deploy che i fix siano attivi (read-only) | `DOMAIN`, `BACKEND`, `HMAC_SECRET` |

## Prerequisiti
- `openssl` (gen-secrets)
- **Foundry** `cast` nel PATH (set-oracle-*): `curl -L https://foundry.paradigm.xyz | bash && foundryup`
- `derive-kms-*`: vai dove il backend ha le deps + le credenziali AWS (shell Render o venv locale con boto3)
- `OWNER_KEY` = chiave dell'**owner** dei contratti, idealmente da hardware/cold wallet

## Flusso tipico
```bash
chmod +x ops/*.sh

# 1) Segreti → incollali in Render (backend) e Vercel (frontend)
./ops/gen-secrets.sh

# 2) (M1-A) Sposta l'oracle in KMS sul rail V4 vivo
export ORACLE_SIGNER_MODE=kms AWS_REGION=eu-west-1 ORACLE_KMS_KEY_ID=<id>
KMS_ADDR=$(./ops/derive-kms-oracle-address.sh | head -1)
V4_ADDR=0x<router> RPC_URL=https://mainnet.base.org OWNER_KEY=0x<owner> \
  KMS_ADDR=$KMS_ADDR ./ops/set-oracle-signer-v4.sh
#   poi: ORACLE_SIGNER_MODE=remote (Vercel), ORACLE_SIGNER_MODE=kms+ORACLE_KMS_KEY_ID (Render)

# 3) (M1-B, opzionale) Multisig: deploy V6 (forge), poi:
V6_ADDR=0x<v6> SIGNERS="0xaaa,0xbbb,0xccc" THRESHOLD=2 \
  RPC_URL=https://mainnet.base.org OWNER_KEY=0x<owner> ./ops/set-oracle-signers-v6.sh
#   poi: NEXT_PUBLIC_FEE_ROUTER_V4_<CHAIN>=<v6> + version:'v6' in lib/contractRegistry.ts

# 4) Dopo il deploy: verifica
DOMAIN=https://app.example.com BACKEND=https://backend.example.com \
  HMAC_SECRET=<hmac> ./ops/smoke-test.sh
```

> ⚠️ Gli script che fanno `cast send` muovono transazioni on-chain con la
> `OWNER_KEY`: usali con consapevolezza, su una rete e un contratto verificati.
