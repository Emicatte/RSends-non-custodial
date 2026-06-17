"""GitHub OAuth token verification + profile fetching.

Verifies a user access_token by calling GitHub's REST API:
  - GET /user        base profile (id, login, avatar_url, name, email-if-public)
  - GET /user/emails all emails including private — used to resolve a
                     primary+verified email when /user hides it.

Returns `GitHubProfile` or raises `GitHubOAuthError(code, detail)`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx


log = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TIMEOUT_SECONDS = 5.0


class GitHubOAuthError(Exception):
    """Structured error for GitHub OAuth flow.

    `code` is machine-readable and maps to i18n keys client-side
    (prefixed `github_` at the route layer).
    """

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass
class GitHubProfile:
    sub: str
    email: str
    email_verified: bool
    username: str
    avatar_url: Optional[str] = None
    display_name: Optional[str] = None


def _pick_primary_email(emails: list) -> Optional[dict]:
    for e in emails:
        if e.get("primary") and e.get("verified"):
            return e
    for e in emails:
        addr = str(e.get("email", "")).lower()
        if e.get("verified") and "noreply" not in addr:
            return e
    return None


async def verify_github_access_token(access_token: str) -> GitHubProfile:
    """Verify access_token with GitHub and return enriched profile.

    Raises GitHubOAuthError with codes:
      - invalid_token      401 from GitHub or malformed input
      - no_verified_email  user has no usable verified email
      - github_api_error   non-200 from /user
      - network_error      httpx timeout / connection failure
      - invalid_response   missing id/login or malformed payload
    """
    if not access_token or len(access_token) < 20:
        raise GitHubOAuthError("invalid_token", "access_token missing or malformed")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "rsend-backend",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT_SECONDS) as client:
            user_resp = await client.get(
                f"{GITHUB_API_BASE}/user", headers=headers
            )
            if user_resp.status_code == 401:
                raise GitHubOAuthError("invalid_token", "github rejected token")
            if user_resp.status_code != 200:
                log.warning(
                    "github_user_non_200",
                    extra={"status": user_resp.status_code},
                )
                raise GitHubOAuthError(
                    "github_api_error", f"status {user_resp.status_code}"
                )

            user_data = user_resp.json()
            sub = str(user_data.get("id", "")) if user_data.get("id") else ""
            username = user_data.get("login") or ""
            if not sub or not username:
                raise GitHubOAuthError("invalid_response", "missing id or login")

            avatar_url = user_data.get("avatar_url")
            display_name = user_data.get("name")

            emails_resp = await client.get(
                f"{GITHUB_API_BASE}/user/emails", headers=headers
            )
            if emails_resp.status_code != 200:
                raise GitHubOAuthError(
                    "no_verified_email",
                    f"cannot fetch /user/emails (status {emails_resp.status_code})",
                )

            emails_payload = emails_resp.json()
            if not isinstance(emails_payload, list):
                raise GitHubOAuthError("invalid_response", "emails list malformed")

            chosen = _pick_primary_email(emails_payload)
            if chosen is None:
                raise GitHubOAuthError(
                    "no_verified_email", "no primary verified email found"
                )

            email = str(chosen["email"]).lower()

            return GitHubProfile(
                sub=sub,
                email=email,
                email_verified=True,
                username=username,
                avatar_url=avatar_url,
                display_name=display_name,
            )

    except GitHubOAuthError:
        raise
    except httpx.TimeoutException as e:
        log.warning("github_timeout", extra={"error": str(e)[:100]})
        raise GitHubOAuthError("network_error", "github timeout")
    except httpx.HTTPError as e:
        log.warning("github_network_error", extra={"error": str(e)[:100]})
        raise GitHubOAuthError("network_error", str(e)[:100])
    except Exception as e:
        log.exception("github_unexpected_error")
        raise GitHubOAuthError("unexpected_error", str(e)[:100])
