"""
RSends Backend — Reconciliation Prometheus Metrics.

Metriche esposte:
  - rsend_ledger_discrepancies_total (counter)
  - rsend_stale_transactions_gauge (gauge)
  - rsend_reconciliation_duration_seconds (histogram)
  - rsend_onchain_discrepancy_total (counter)
"""

from prometheus_client import Counter, Gauge, Histogram

LEDGER_DISCREPANCIES = Counter(
    "rsend_ledger_discrepancies_total",
    "Number of ledger imbalances detected (DEBIT != CREDIT per transaction)",
)

STALE_TRANSACTIONS_GAUGE = Gauge(
    "rsend_stale_transactions_gauge",
    "Current number of transactions stuck in PROCESSING beyond threshold",
)

RECONCILIATION_DURATION = Histogram(
    "rsend_reconciliation_duration_seconds",
    "Time spent running the full reconciliation job",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)

ONCHAIN_DISCREPANCY = Counter(
    "rsend_onchain_discrepancy_total",
    "Number of on-chain balance discrepancies detected",
)
