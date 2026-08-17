"""The SINGLE definition of "approved enough" — shared by every approval gate.

Two surfaces enforce org approval (`require_org_approved` for the session/`/app`
routes, `require_approved_merchant` for the merchant API-key router) and the
live-key mint guard needs the same rule. They all call `approval_denial` here,
so the policy cannot drift into three subtly different answers.

The policy is ENVIRONMENT-SCOPED (2026-08-08 product decision — KYB self-service,
zero human wait):

    sandbox ("test")  -> a submitted company profile IS the gate. A merchant
                         sitting in `pending_approval` gets full testnet access
                         immediately; no operator has to act. Testnet settles
                         faucet tokens through the Base Sepolia router — there
                         is no real money to protect, and making a partner wait
                         on a human before they can evaluate the API was the
                         single biggest drag on integration.
    live              -> UNCHANGED: `approval_status == 'approved'` is required,
                         and anything unknown/missing fails closed. This is
                         where real funds move.

`declined` blocks in BOTH environments: it is an explicit operator decision and
must stay enforceable, never merely advisory.

What this does NOT relax:
  - the KYB gate. `require_org_approved` still demands
    `onboarding_status == 'company_submitted'` BEFORE consulting this policy,
    so the company profile (legal name, registration number, VAT, declarations)
    is still collected up front.
  - tenant resolution. A caller whose org cannot be resolved unambiguously is
    denied by the caller itself, before this policy is ever consulted.
"""

from __future__ import annotations

from fastapi import HTTPException

# The environment whose access is gated by KYB alone. `/app` and the
# session-minted merchant keys are hard-pinned to it today
# (user_org_merchant_keys_routes.ENVIRONMENT).
SANDBOX_ENVIRONMENT = "test"

# Sandbox access is an ALLOWLIST, not "anything that isn't declined" — unknown
# or missing states still fail closed. This matters for the future: if a
# `suspended` / `revoked` status is ever added, it blocks the sandbox by
# default and someone has to decide, deliberately, to let it through.
_SANDBOX_ALLOWED = frozenset({"pending_approval", "approved"})


def approval_denial(
    approval_status: str | None,
    *,
    environment: str,
    decline_reason: str | None = None,
) -> HTTPException | None:
    """The exception to raise for this (status, environment), or None to allow.

    Returning rather than raising keeps the decision testable in isolation and
    lets each caller add its own context before raising.
    """
    if approval_status == "declined":
        detail: dict = {"code": "approval_declined"}
        if decline_reason:
            detail["reason"] = decline_reason
        return HTTPException(status_code=403, detail=detail)

    if environment == SANDBOX_ENVIRONMENT:
        # Sandbox: KYB was the gate and it already passed. `pending_approval`
        # goes through; unknown states still don't.
        if approval_status in _SANDBOX_ALLOWED:
            return None
        return HTTPException(status_code=403, detail={"code": "approval_pending"})

    # Live: fail closed on anything that is not an explicit approval.
    if approval_status == "approved":
        return None
    return HTTPException(status_code=403, detail={"code": "approval_pending"})
