# RPagos Backend — Deployment Guide

## Architettura

```
Internet
   │
   ├─ Nginx (SSL + Rate Limit + Load Balancing)
   │     │
   │     ├─ API Container #1 (FastAPI, 4 workers)
   │     ├─ API Container #2 (FastAPI, 4 workers)
   │     │
   │     ├─ Redis (Cache + Rate Limiting)
   │     └─ PostgreSQL (Persistent Data)
   │
   ├─ Prometheus → Grafana (Monitoring)
   └─ Sentry (Error Tracking)
```

## Quick Start (Locale)

```bash
cd rpagos-backend
cp .env.example .env
# Compila i valori in .env

docker-compose up -d
# API disponibile su http://localhost:80
# Grafana su http://localhost:3001
```

## Deploy su Cloud

### Opzione 1: DigitalOcean App Platform (Consigliata)

1. Crea un account su digitalocean.com
2. Create App → From Docker Hub o GitHub
3. Aggiungi PostgreSQL e Redis come "Add-ons"
4. Imposta le env variables dal pannello
5. Deploy automatico ad ogni push su main

Costo: ~$12/mese (1 container + DB managed + Redis)

### Opzione 2: Railway.app (Più semplice)

1. Collega il repo GitHub
2. Railway detecta il Dockerfile automaticamente
3. Aggiungi PostgreSQL e Redis dal marketplace
4. Le env variables si auto-configurano

Costo: ~$5-15/mese usage-based

### Opzione 3: AWS (Enterprise)

1. Push Docker image su ECR
2. Deploy su ECS Fargate (serverless containers)
3. RDS per PostgreSQL, ElastiCache per Redis
4. ALB per load balancing + SSL

Costo: ~$30-50/mese (auto-scaling incluso)

## SSL con Let's Encrypt

```bash
# Installa certbot
sudo apt install certbot

# Genera certificati
sudo certbot certonly --standalone -d api.rpagos.io

# Copia in nginx/ssl/
cp /etc/letsencrypt/live/api.rpagos.io/fullchain.pem nginx/ssl/
cp /etc/letsencrypt/live/api.rpagos.io/privkey.pem nginx/ssl/

# Riavvia nginx
docker-compose restart nginx
```

## Scaling

Per gestire 1000+ utenti simultanei:

```yaml
# In docker-compose.yml, aumenta le repliche:
deploy:
  replicas: 4  # 4 container × 4 workers = 16 processi paralleli
```

## Monitoring

- **Grafana**: http://localhost:3001 (admin / password dal .env)
- **Prometheus**: metriche raw su /metrics
- **Sentry**: errori in tempo reale con stack trace

## Database Migration (Alembic)

```bash
# Genera una nuova migration
docker-compose exec api alembic revision --autogenerate -m "descrizione"

# Applica
docker-compose exec api alembic upgrade head
```

## Comandi Utili

```bash
# Logs in tempo reale
docker-compose logs -f api

# Stato dei container
docker-compose ps

# Rebuild dopo modifiche
docker-compose up -d --build

# Backup database
docker-compose exec db pg_dump -U rpagos rpagos > backup.sql

# Redis CLI
docker-compose exec redis redis-cli
```
