"""
RSends Backend — Centralized Prometheus Metrics.

All application-level metrics in one place. Import this module from
any service that needs to record metrics.

Existing metrics (defined elsewhere, re-exported here for discovery):
  - sweep_total (sweep_service.py)
  - sweep_latency_seconds (sweep_service.py)
  - sweep_amount_eth (sweep_service.py)
  - sweep_gas_gwei (sweep_service.py)
  - active_rules_total (sweep_service.py)
  - circuit_breaker_state (circuit_breaker.py)
  - circuit_breaker_failures_total (circuit_breaker.py)
  - circuit_breaker_successes_total (circuit_breaker.py)
  - circuit_breaker_transitions_total (circuit_breaker.py)
  - rsend_ledger_discrepancies_total (reconciliation_metrics.py)
  - rsend_stale_transactions_gauge (reconciliation_metrics.py)
  - rsend_reconciliation_duration_seconds (reconciliation_metrics.py)
  - rsend_onchain_discrepancy_total (reconciliation_metrics.py)

New metrics (CC-12):
  - rsend_sweep_batches_total
  - rsend_sweep_duration_seconds
  - rsend_sweep_recipients_total
  - rsend_sweep_amount_wei
  - rsend_sweep_gas_used_total
  - rsend_spending_usage_ratio
  - rsend_hot_wallet_balance_wei
  - rsend_celery_queue_depth
  - rsend_websocket_connections
  - rsend_webhook_received_total
  - rsend_webhook_processed_total
  - rsend_webhook_rejected_total
  - rsend_notifications_sent_total
  - rsend_notifications_failed_total
  - rsend_notifications_rate_limited_total
"""

from prometheus_client import Counter, Gauge, Histogram


# ═══════════════════════════════════════════════════════════════
#  Sweep Pipeline
# ═══════════════════════════════════════════════════════════════

SWEEP_BATCHES_TOTAL = Counter(
    "rsend_sweep_batches_total",
    "Total sweep batches by final status",
    ["status", "chain_id"],
)

SWEEP_DURATION_SECONDS = Histogram(
    "rsend_sweep_duration_seconds",
    "End-to-end sweep batch execution time",
    ["chain_id"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300],
)

SWEEP_RECIPIENTS_TOTAL = Counter(
    "rsend_sweep_recipients_total",
    "Total recipients across all sweep batches",
    ["chain_id"],
)

SWEEP_AMOUNT_WEI = Counter(
    "rsend_sweep_amount_wei",
    "Total amount swept in Wei",
    ["chain_id", "token"],
)

SWEEP_GAS_USED_TOTAL = Counter(
    "rsend_sweep_gas_used_total",
    "Total gas used by sweep transactions (wei)",
    ["chain_id"],
)


# ═══════════════════════════════════════════════════════════════
#  Nonce Management
# ═══════════════════════════════════════════════════════════════

NONCE_GAPS_ON_STARTUP = Counter(
    "rsend_nonce_gaps_on_startup",
    "Number of times the sweeper restarted with a nonce gap (pending TXes in mempool)",
    ["chain_id"],
)


# ═══════════════════════════════════════════════════════════════
#  Spending & Wallet
# ═══════════════════════════════════════════════════════════════

SPENDING_USAGE_RATIO = Gauge(
    "rsend_spending_usage_ratio",
    "Current spending usage as ratio (0.0 - 1.0) by tier",
    ["tier", "source"],
)

HOT_WALLET_BALANCE_WEI = Gauge(
    "rsend_hot_wallet_balance_wei",
    "Hot wallet balance in Wei",
    ["chain_id"],
)


# ═══════════════════════════════════════════════════════════════
#  Infrastructure
# ═══════════════════════════════════════════════════════════════

CELERY_QUEUE_DEPTH = Gauge(
    "rsend_celery_queue_depth",
    "Number of tasks waiting in Celery queue",
    ["queue"],
)

WEBSOCKET_CONNECTIONS = Gauge(
    "rsend_websocket_connections",
    "Active WebSocket connections",
)


# ═══════════════════════════════════════════════════════════════
#  Webhooks
# ═══════════════════════════════════════════════════════════════

WEBHOOK_RECEIVED_TOTAL = Counter(
    "rsend_webhook_received_total",
    "Total webhooks received from external sources",
    ["source"],
)

WEBHOOK_PROCESSED_TOTAL = Counter(
    "rsend_webhook_processed_total",
    "Webhooks successfully processed",
    ["source"],
)

WEBHOOK_REJECTED_TOTAL = Counter(
    "rsend_webhook_rejected_total",
    "Webhooks rejected (auth failed, invalid payload, etc.)",
    ["source", "reason"],
)


# ═══════════════════════════════════════════════════════════════
#  Notifications
# ═══════════════════════════════════════════════════════════════

NOTIFICATIONS_SENT_TOTAL = Counter(
    "rsend_notifications_sent_total",
    "Total notifications successfully sent",
    ["type", "channel"],
)

NOTIFICATIONS_FAILED_TOTAL = Counter(
    "rsend_notifications_failed_total",
    "Total notification send failures",
    ["type", "channel"],
)

NOTIFICATIONS_RATE_LIMITED_TOTAL = Counter(
    "rsend_notifications_rate_limited_total",
    "Total notifications dropped due to rate limiting",
    ["channel"],
)
