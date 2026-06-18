"""Trusted proxy list and real-client-IP extraction.

X-Forwarded-For and X-Real-IP headers are only trustworthy if the
immediate TCP connection is from a trusted reverse proxy (ALB,
Cloudflare, nginx). Otherwise any client can spoof these headers
to bypass rate limits, IP allowlists, and poison audit logs.

Configure via env var TRUSTED_PROXIES (comma-separated CIDRs).
Default: localhost only (safe for dev, explicit config needed for prod).
"""

import ipaddress
import logging
import os
from typing import Union

from starlette.requests import Request

logger = logging.getLogger(__name__)

_Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


def _parse_trusted_proxies() -> list[_Network]:
    raw = os.getenv("TRUSTED_PROXIES", "127.0.0.1/32,::1/128").strip()
    networks: list[_Network] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            if "/" not in entry:
                entry = entry + ("/32" if ":" not in entry else "/128")
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as e:
            logger.warning("Invalid TRUSTED_PROXIES entry '%s': %s", entry, e)
    return networks


_TRUSTED_NETWORKS: list[_Network] = _parse_trusted_proxies()


def _is_trusted_proxy(ip_str: str) -> bool:
    if not ip_str or ip_str == "unknown":
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in net for net in _TRUSTED_NETWORKS)
    except ValueError:
        return False


def get_real_client_ip(request: Request) -> str:
    """Return the real client IP, respecting forwarded headers only
    when the immediate connection is from a trusted proxy."""
    direct_ip = request.client.host if request.client else "unknown"

    if not _is_trusted_proxy(direct_ip):
        return direct_ip

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client = forwarded.split(",")[0].strip()
        if client:
            return client

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    return direct_ip
