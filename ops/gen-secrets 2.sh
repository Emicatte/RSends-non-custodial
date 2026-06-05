#!/usr/bin/env bash
# Genera i segreti per il go-live (sez. 1 del GO_LIVE_RUNBOOK).
# Stampa i valori — copiali nei pannelli Render (backend) e Vercel (frontend).
# NB: INTERNAL_PROXY_SECRET e HMAC_SECRET vanno IDENTICI sui due lati.
set -euo pipefail

echo "INTERNAL_PROXY_SECRET=$(openssl rand -hex 32)   # IDENTICO su backend e Next"
echo "HMAC_SECRET=$(openssl rand -hex 32)             # = valore di X-Admin-Token"
echo "ADMIN_SECRET=$(openssl rand -hex 32)            # password dashboard admin"
echo "AUTH_JWT_SECRET=$(openssl rand -hex 32)         # 64 char (>=64 richiesto in prod)"
