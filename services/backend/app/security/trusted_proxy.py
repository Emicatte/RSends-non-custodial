"""Trusted proxy list and real-client-IP extraction.

X-Forwarded-For and X-Real-IP headers are only trustworthy if the
immediate TCP connection is from a trusted reverse proxy (ALB,
Cloudflare, nginx). Otherwise any client can spoof these headers
to bypass rate limits, IP allowlists, and poison audit logs.

Configure via env var TRUSTED_PROXIES (comma-separated CIDRs).
Default: localhost only (safe for dev, explicit config needed for prod).

There is a second, independent mechanism for the one hop that a CIDR list
cannot describe: the web app's proxy routes. Those run on Vercel, whose egress
IPs rotate, so there is no stable network to put in TRUSTED_PROXIES — and the
backend's own URL is reachable directly (no TrustedHostMiddleware), so trusting
the leftmost X-Forwarded-For entry would let anyone with curl choose their own
rate-limit bucket and forge audit rows. Instead the proxy proves it is ours by
presenting the shared INTERNAL_PROXY_SECRET alongside the address it observed.
See CLIENT_IP_HEADER below.
"""

import ipaddress
import logging
import os
import secrets
from typing import Optional, Union

from starlette.requests import Request

logger = logging.getLogger(__name__)

_Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]

#: The address our own edge proxy observed for the browser, and the proof that
#: the caller really is that proxy. Both must be present for either to count.
CLIENT_IP_HEADER = "X-RSend-Client-IP"
PROXY_SECRET_HEADER = "X-RSend-Proxy-Secret"

_secret_mismatch_warned = False


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


def _claimed_client_ip(request: Request) -> Optional[str]:
    """The address our edge proxy observed, if the caller can prove it is that
    proxy. Returns None — never raises, never guesses — in every other case.

    Read from the environment per call rather than at import: unlike the CIDR
    list this is a secret an operator may rotate, and a stale process-lifetime
    copy of it is a debugging trap.
    """
    global _secret_mismatch_warned

    claimed = (request.headers.get(CLIENT_IP_HEADER) or "").strip()
    if not claimed:
        return None

    configured = os.getenv("INTERNAL_PROXY_SECRET", "").strip()
    presented = (request.headers.get(PROXY_SECRET_HEADER) or "").strip()

    # Fail closed on an unconfigured secret: an empty configured value must not
    # be matchable by an empty presented one.
    if not configured or not presented or not secrets.compare_digest(presented, configured):
        if not _secret_mismatch_warned:
            _secret_mismatch_warned = True
            logger.warning(
                "%s presented without a valid %s — falling back to the socket "
                "peer. If this is our own proxy, INTERNAL_PROXY_SECRET does not "
                "match between the web app and the backend, and every per-IP "
                "rate limit is collapsing into one bucket.",
                CLIENT_IP_HEADER,
                PROXY_SECRET_HEADER,
            )
        return None

    # A valid secret does not make arbitrary text an address. This value ends up
    # in rate-limit keys and audit rows.
    try:
        ipaddress.ip_address(claimed)
    except ValueError:
        logger.warning("Malformed %s from an authenticated proxy — ignoring", CLIENT_IP_HEADER)
        return None

    return claimed


def get_real_client_ip(request: Request) -> str:
    """Return the real client IP, respecting forwarded headers only
    when the immediate connection is from a trusted proxy."""
    proven = _claimed_client_ip(request)
    if proven:
        return proven

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
