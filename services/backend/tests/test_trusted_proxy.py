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

from app.security.trusted_proxy import get_real_client_ip, _is_trusted_proxy


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
    req = Mock()
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
