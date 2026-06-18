"""
RPagos Backend — External Services Health Monitor

Aggregates health status from all circuit breakers to provide
a unified view of external dependency health.

Exposed via GET /health/dependencies in main.py.
"""

import logging
from typing import Literal

from app.services.circuit_breaker import (
    get_all_circuit_breakers,
    get_circuit_breaker,
    CBState,
)

logger = logging.getLogger(__name__)

HealthStatus = Literal["healthy", "degraded", "down"]


def _cb_state_to_health(state: CBState) -> HealthStatus:
    """Map circuit breaker state to a health status string."""
    if state == CBState.CLOSED:
        return "healthy"
    elif state == CBState.HALF_OPEN:
        return "degraded"
    else:
        return "down"


async def check_all_dependencies() -> dict[str, dict]:
    """
    Check health of all registered external services.

    Returns a dict keyed by service name:
        {
            "alchemy_rpc": {"status": "healthy", "failures": 0, ...},
            "redis":       {"status": "degraded", "failures": 3, ...},
            "telegram":    {"status": "down", "failures": 5, ...},
        }
    """
    all_cbs = get_all_circuit_breakers()
    results: dict[str, dict] = {}

    for name, cb in all_cbs.items():
        info = cb.info()
        results[name] = {
            "status": _cb_state_to_health(CBState(info["state"])),
            "circuit_state": info["state"],
            "failures": info["failure_count"],
            "failure_threshold": info["failure_threshold"],
            "recovery_timeout_s": info["recovery_timeout"],
        }

    return results


async def get_dependency_summary() -> dict:
    """
    Get a summary suitable for the /health/dependencies endpoint.

    Returns:
        {
            "overall": "healthy" | "degraded" | "down",
            "services": { ... per-service detail ... }
        }
    """
    services = await check_all_dependencies()

    from app.services.cache_service import get_redis_cb_state
    rcb = get_redis_cb_state()
    services["redis_connection"] = {
        "status": (
            "healthy" if rcb["state"] == "closed"
            else "degraded" if rcb["state"] == "half_open"
            else "down"
        ),
        "circuit_state": rcb["state"],
        "failures": rcb["failure_count"],
    }

    if not services:
        return {"overall": "healthy", "services": {}}

    statuses = [s["status"] for s in services.values()]

    if all(s == "healthy" for s in statuses):
        overall: HealthStatus = "healthy"
    elif any(s == "down" for s in statuses):
        overall = "degraded"
    else:
        overall = "degraded"

    return {
        "overall": overall,
        "services": services,
    }
