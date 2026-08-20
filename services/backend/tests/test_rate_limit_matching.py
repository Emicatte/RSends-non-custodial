"""_match_endpoint returns the FIRST matching prefix, so ENDPOINT_LIMITS must be
ordered most-specific-prefix-first. Regression guard for the pre-existing bug
where the bare `payment-intent` (create, 100/60) prefix shadowed the stricter
`payment-intent/` (cancel/resolve, 10/60) subpath, making the latter dead code.
"""

from app.middleware.rate_limit import _match_endpoint


def test_create_intent_uses_create_limit():
    assert _match_endpoint("POST", "/api/v1/merchant/payment-intent") == (100, 60, "api_key")


def test_cancel_uses_stricter_subpath_limit():
    # Previously shadowed to 100/60 by the bare prefix — must be 10/60.
    limit = _match_endpoint("POST", "/api/v1/merchant/payment-intent/pi_abc/cancel")
    assert limit == (10, 60, "api_key")


def test_resolve_uses_stricter_subpath_limit():
    limit = _match_endpoint("POST", "/api/v1/merchant/payment-intent/pi_abc/resolve")
    assert limit == (10, 60, "api_key")


def test_get_intent_by_id_uses_get_subpath_limit():
    limit = _match_endpoint("GET", "/api/v1/merchant/payment-intent/pi_abc")
    assert limit == (60, 60, "api_key")


def test_org_patch_has_explicit_ip_limit():
    assert _match_endpoint("PATCH", "/api/v1/organizations/00000000-0000-0000-0000-000000000000") == (30, 60, "ip")


def test_volume_series_subpath_not_shadowed_by_bare_stats_prefix():
    """`/user/org/stats` is a prefix of `/user/org/stats/volume-series`, so the
    bare entry MUST sit BELOW the subpath one or the subpath becomes dead code
    — the exact bug this module guards for payment-intent."""
    assert _match_endpoint(
        "GET", "/api/v1/user/org/stats/volume-series"
    ) == (60, 60, "ip")


def test_bare_org_stats_still_matches_its_own_limit():
    assert _match_endpoint("GET", "/api/v1/user/org/stats") == (120, 60, "ip")
