"""Current legal document versions — the single source of truth.

Consent records store the version a user accepted; `consents_current`
compares the latest record per document against these constants by string
equality (versions are opaque labels, not ordered). Bumping a value here is
the ENTIRE re-consent trigger: on next navigation the onboarding guard
routes previously consented users back to the consent step. No other
machinery.

"draft-1" marks the placeholder texts; replacing them with the final legal
documents (and bumping these versions) is a pre-production launch blocker
owned outside the codebase.
"""

TOS_VERSION = "draft-1"
PRIVACY_VERSION = "draft-1"

CURRENT_VERSIONS: dict[str, str] = {
    "tos": TOS_VERSION,
    "privacy": PRIVACY_VERSION,
}
