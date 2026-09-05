"""
Test: Trusted proxy IP extraction (Fix 8.3).

Verifies that X-Forwarded-For / X-Real-IP headers are only trusted
when the direct TCP connection is from a trusted reverse proxy.

Run:
  cd rpagos-backend
  pytest tests/test_trusted_proxy.py -v
"""

import ipaddress
from unittest.mock import Mock, patch

from app.security.trusted_proxy import (
    CLIENT_IP_HEADER,
    PROXY_SECRET_HEADER,
    get_real_client_ip,
    _is_trusted_proxy,
)


def _mock_request(direct_ip: str, headers: dict = None) -> Mock:
    req = Mock()
    req.client.host = direct_ip
    _headers = headers or {}
    req.headers.get = lambda k, default="": _headers.get(k, default)
    return req


LOCALHOST_NETS = [
    ipaddress.ip_network("127.0.0.1/32"),
    ipaddress.ip_network("::1/128"),
]

ALB_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.1/32"),
    ipaddress.ip_network("::1/128"),
]


def test_ignores_xff_when_direct_ip_not_trusted():
    """Attacker setting X-Forwarded-For from untrusted source is ignored."""
    req = _mock_request(
        direct_ip="198.51.100.1",
        headers={"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "5.6.7.8"},
    )
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "198.51.100.1"


def test_ignores_x_real_ip_when_direct_ip_not_trusted():
    """X-Real-IP from untrusted source is ignored."""
    req = _mock_request(
        direct_ip="203.0.113.50",
        headers={"X-Real-IP": "10.0.0.1"},
    )
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "203.0.113.50"


def test_trusts_xff_when_direct_ip_is_trusted():
    """Legitimate proxy chain: X-Forwarded-For first entry is returned."""
    req = _mock_request(
        direct_ip="10.0.5.1",
        headers={"X-Forwarded-For": "203.0.113.1, 10.0.5.1"},
    )
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", ALB_NETS):
        assert get_real_client_ip(req) == "203.0.113.1"


def test_trusts_x_real_ip_when_trusted_and_no_xff():
    """Trusted proxy with X-Real-IP but no X-Forwarded-For."""
    req = _mock_request(
        direct_ip="10.0.1.1",
        headers={"X-Real-IP": "198.51.100.99"},
    )
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", ALB_NETS):
        assert get_real_client_ip(req) == "198.51.100.99"


def test_falls_back_to_direct_when_no_headers():
    """Trusted proxy but no forwarded headers → returns direct IP."""
    req = _mock_request(direct_ip="127.0.0.1")
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "127.0.0.1"


def test_localhost_trusted_by_default():
    """127.0.0.1 is trusted with default config."""
    assert _is_trusted_proxy("127.0.0.1") is True


def test_untrusted_unknown_ip():
    """'unknown' as direct IP is not trusted."""
    assert _is_trusted_proxy("unknown") is False


def test_no_client_returns_unknown():
    """Request with no client info returns 'unknown'."""
    # Headers are modelled explicitly (a bare Mock would hand every lookup back
    # another Mock, which no Starlette request ever does).
    req = _mock_request(direct_ip="unused", headers={})
    req.client = None
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "unknown"


def test_xff_single_ip_from_trusted_proxy():
    """X-Forwarded-For with a single IP (no comma) from trusted proxy."""
    req = _mock_request(
        direct_ip="127.0.0.1",
        headers={"X-Forwarded-For": "192.168.1.100"},
    )
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "192.168.1.100"


# ═══════════════════════════════════════════════════════════════
#  Secret-gated client-IP header (the RSends edge proxy hop)
#
#  Vercel's egress IPs rotate, so there is no stable CIDR set to put in
#  TRUSTED_PROXIES for the web→backend hop, and the backend's Render URL is
#  reachable directly (no TrustedHostMiddleware). A CIDR allowlist plus
#  leftmost-XFF parsing would therefore be spoofable by anyone with curl.
#  Instead the proxy proves it is ours with the shared INTERNAL_PROXY_SECRET;
#  the claimed IP is honoured only then.
# ═══════════════════════════════════════════════════════════════

SECRET = "s" * 48


def _secret_request(direct_ip: str, claimed_ip: str, presented_secret=None, **extra):
    headers = {CLIENT_IP_HEADER: claimed_ip}
    if presented_secret is not None:
        headers[PROXY_SECRET_HEADER] = presented_secret
    headers.update(extra)
    return _mock_request(direct_ip=direct_ip, headers=headers)


def test_claimed_ip_honoured_when_proxy_secret_matches(monkeypatch):
    """The happy path: our edge proxy forwards the payer's IP and proves it."""
    monkeypatch.setenv("INTERNAL_PROXY_SECRET", SECRET)
    req = _secret_request("198.51.100.7", "203.0.113.42", SECRET)
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "203.0.113.42"


def test_claimed_ip_ignored_without_the_secret_header(monkeypatch):
    """A direct-to-backend caller sets the IP header but has no secret."""
    monkeypatch.setenv("INTERNAL_PROXY_SECRET", SECRET)
    req = _secret_request("198.51.100.7", "203.0.113.42", presented_secret=None)
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "198.51.100.7"


def test_claimed_ip_ignored_when_secret_is_wrong(monkeypatch):
    monkeypatch.setenv("INTERNAL_PROXY_SECRET", SECRET)
    req = _secret_request("198.51.100.7", "203.0.113.42", "w" * 48)
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "198.51.100.7"


def test_claimed_ip_ignored_when_backend_secret_is_unset(monkeypatch):
    """Fail closed: no configured secret means the header can never be trusted,
    even if the caller presents an empty one that would 'match'."""
    monkeypatch.delenv("INTERNAL_PROXY_SECRET", raising=False)
    req = _secret_request("198.51.100.7", "203.0.113.42", "")
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "198.51.100.7"


def test_claimed_ip_ignored_when_backend_secret_is_blank(monkeypatch):
    monkeypatch.setenv("INTERNAL_PROXY_SECRET", "   ")
    req = _secret_request("198.51.100.7", "203.0.113.42", "   ")
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "198.51.100.7"


def test_malformed_claimed_ip_is_rejected(monkeypatch):
    """A valid secret does not make an unparseable value an IP. Rate-limit keys
    and audit rows must never carry attacker-chosen free text."""
    monkeypatch.setenv("INTERNAL_PROXY_SECRET", SECRET)
    req = _secret_request("198.51.100.7", "not-an-ip; DROP TABLE", SECRET)
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "198.51.100.7"


def test_ipv6_claimed_ip_is_accepted(monkeypatch):
    monkeypatch.setenv("INTERNAL_PROXY_SECRET", SECRET)
    req = _secret_request("198.51.100.7", "2001:db8::1", SECRET)
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "2001:db8::1"


def test_secret_header_wins_over_xff_from_a_trusted_peer(monkeypatch):
    """Both mechanisms present: the proven one is authoritative."""
    monkeypatch.setenv("INTERNAL_PROXY_SECRET", SECRET)
    req = _secret_request(
        "127.0.0.1", "203.0.113.42", SECRET, **{"X-Forwarded-For": "192.0.2.9"}
    )
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", LOCALHOST_NETS):
        assert get_real_client_ip(req) == "203.0.113.42"


def test_existing_xff_path_untouched_when_no_claim_header(monkeypatch):
    """Regression: configuring a secret must not change any existing behaviour
    for requests that do not carry the claim header."""
    monkeypatch.setenv("INTERNAL_PROXY_SECRET", SECRET)
    req = _mock_request("10.0.5.1", {"X-Forwarded-For": "203.0.113.1, 10.0.5.1"})
    with patch("app.security.trusted_proxy._TRUSTED_NETWORKS", ALB_NETS):
        assert get_real_client_ip(req) == "203.0.113.1"
