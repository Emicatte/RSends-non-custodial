# ═══════════════════════════════════════════════════════════
#  RPagos Backend — Production Dockerfile
#  Multi-stage build: slim image, non-root user
# ═══════════════════════════════════════════════════════════

FROM python:3.11-slim AS base

# Security: non-root user
RUN groupadd -r rpagos && useradd -r -g rpagos -d /app rpagos

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Create reports directory and tmp for SQLite
RUN mkdir -p /app/reports /tmp/data && chown -R rpagos:rpagos /app /tmp/data

COPY --chown=rpagos:rpagos scripts/entrypoint.sh /app/scripts/entrypoint.sh
RUN chmod +x /app/scripts/entrypoint.sh

USER rpagos

# Health check
# HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
#   CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

EXPOSE 8000

CMD ["/app/scripts/entrypoint.sh"]
