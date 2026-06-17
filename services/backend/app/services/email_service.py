"""Resend email service with retry + dev-mode dry-run + minimal templating.

Environment:
    RESEND_API_KEY   — required when email_dev_mode is False
    EMAIL_FROM       — From header (default "security@rsends.io")
    EMAIL_DEV_MODE   — if True, log the would-be send and skip HTTP
    FRONTEND_URL     — used inside templates for CTA links

send_email() never raises. Failures return None so callers (celery tasks,
auth hooks) can absorb them silently — an email hiccup must not break login.
"""

import logging
from html import escape
from pathlib import Path
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "emails"


def _load_template(name: str, context: dict) -> str:
    """Read `{name}.html` and substitute `{{key}}` placeholders.

    Values are HTML-escaped so user-controlled strings (display_name, etc.)
    can't break out of the template. Intentionally minimal — no Jinja2 dep.
    """
    path = TEMPLATE_DIR / f"{name}.html"
    html = path.read_text(encoding="utf-8")
    for key, value in context.items():
        html = html.replace(f"{{{{{key}}}}}", escape(str(value)))
    return html


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    reraise=True,
)
async def _send_via_resend(
    to: str, subject: str, html_body: str, from_addr: str, api_key: str
) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": from_addr,
                "to": [to],
                "subject": subject,
                "html": html_body,
            },
        )
        if resp.status_code >= 400:
            log.error(
                "resend_api_error",
                extra={
                    "status": resp.status_code,
                    "body": resp.text[:500],
                    "to_domain": to.split("@")[-1] if "@" in to else "-",
                },
            )
            resp.raise_for_status()
        return resp.json()


async def send_email(
    to: str,
    template_name: str,
    subject: str,
    context: dict,
) -> Optional[str]:
    """Send an email via Resend. Returns the Resend email id or None on failure.

    Never raises.
    """
    settings = get_settings()

    if settings.email_dev_mode:
        log.info(
            "email_dev_mode_skip",
            extra={
                "to_domain": to.split("@")[-1] if "@" in to else "-",
                "template": template_name,
                "subject": subject,
            },
        )
        return "dev-mode-skip"

    if not settings.resend_api_key:
        log.error(
            "email_api_key_missing",
            extra={"template": template_name},
        )
        return None

    try:
        html_body = _load_template(template_name, context)
    except FileNotFoundError:
        log.error(
            "email_template_not_found",
            extra={"template": template_name},
        )
        return None

    from_addr = settings.email_from or "onboarding@resend.dev"

    try:
        result = await _send_via_resend(
            to=to,
            subject=subject,
            html_body=html_body,
            from_addr=from_addr,
            api_key=settings.resend_api_key,
        )
        email_id = result.get("id")
        log.info(
            "email_sent",
            extra={
                "to_domain": to.split("@")[-1] if "@" in to else "-",
                "template": template_name,
                "email_id": email_id,
            },
        )
        return email_id
    except Exception as e:
        log.exception(
            "email_send_failed",
            extra={
                "to_domain": to.split("@")[-1] if "@" in to else "-",
                "template": template_name,
                "error": str(e)[:200],
            },
        )
        return None
