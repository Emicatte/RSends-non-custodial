"""Stable device fingerprint from UA family + IP /24 subnet + user_id.

Design rationale:
- Full IP changes across Wi-Fi/cellular → use /24 subnet (same ISP/geo area
  typically) so a phone bouncing between networks doesn't trigger an email
  every coffee shop.
- User-Agent changes on browser minor updates → take only browser family
  + OS family, not the full version string.
- Salt with user_id so the same device fingerprints differently for two
  accounts sharing one browser.
"""

import hashlib
import re


_BROWSERS = ("Edge", "Chrome", "Firefox", "Safari", "Opera")


def _extract_ua_signature(user_agent: str) -> str:
    """Return `"{Browser}-{os_family}"` from a UA string.

    Order matters: check "Edge" before "Chrome" (Edge UAs contain Chrome/).
    Falls back to "unknown-unknown" on empty/missing parts.
    """
    if not user_agent:
        return "unknown-unknown"
    ua = user_agent[:500]

    browser = "unknown"
    for b in _BROWSERS:
        if b in ua:
            browser = b
            break

    os_fam = "unknown"
    if "iPhone" in ua or "iPad" in ua:
        os_fam = "ios"
    elif "Android" in ua:
        os_fam = "android"
    elif "Macintosh" in ua or "Mac OS X" in ua:
        os_fam = "macos"
    elif "Windows" in ua:
        os_fam = "windows"
    elif "Linux" in ua:
        os_fam = "linux"

    return f"{browser}-{os_fam}"


def _ip_subnet(ip: str) -> str:
    """IPv4 → `/24`, IPv6 → first 3 hextets + `::/48`, else `unknown`."""
    if not ip:
        return "unknown"
    m = re.match(r"^(\d{1,3}\.\d{1,3}\.\d{1,3})\.\d{1,3}$", ip)
    if m:
        return m.group(1) + ".0/24"
    if ":" in ip:
        parts = ip.split(":")[:3]
        return ":".join(parts) + "::/48"
    return "unknown"


def compute_fingerprint(user_id: str, user_agent: str, ip: str) -> str:
    """Deterministic SHA-256 fingerprint over (user_id | UA family | IP subnet)."""
    ua_sig = _extract_ua_signature(user_agent)
    subnet = _ip_subnet(ip)
    raw = f"{user_id}|{ua_sig}|{subnet}"
    return hashlib.sha256(raw.encode()).hexdigest()


def format_device_label(user_agent: str) -> str:
    """Human-readable device label for the email body (e.g. `"Chrome on Macos"`)."""
    sig = _extract_ua_signature(user_agent or "")
    return sig.replace("-", " on ").title()
