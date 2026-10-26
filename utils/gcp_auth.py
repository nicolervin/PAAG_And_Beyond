"""GCP Identity-Aware Proxy (IAP) and Okta federated identity extraction for PAAG."""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Mapping

try:
    import streamlit as st
except Exception:  # pragma: no cover
    st = None  # type: ignore[assignment]

# Ordered priority of HTTP headers inspected for authenticated user identity
# across GCP IAP (with Google or Okta/Workforce Identity/GCIP federation) and OIDC proxies.
IDENTITY_HEADER_CANDIDATES: tuple[str, ...] = (
    "x-goog-authenticated-user-email",
    "x-okta-user",
    "x-okta-email",
    "x-forwarded-email",
    "x-auth-request-email",
    "oidc-claim-email",
    "x-user-email",
    "x-forwarded-user",
)

JWT_HEADER_CANDIDATES: tuple[str, ...] = (
    "x-goog-iap-jwt-assertion",
    "x-okta-jwt-assertion",
)


def clean_iap_okta_identity(raw_value: str | None) -> str:
    """Normalize an IAP or Okta header value into a clean email or username string.

    Examples handled:
    - 'accounts.google.com:user@example.com' -> 'user@example.com'
    - 'securetoken.google.com/my-proj/okta-oidc:user@example.com' -> 'user@example.com'
    - 'principal://iam.googleapis.com/locations/global/workforcePools/.../subject/user@example.com'
      -> 'user@example.com'
    - 'user@example.com' -> 'user@example.com'
    """
    value = str(raw_value or "").strip()
    if not value:
        return ""

    # If multiple comma-separated values were forwarded, take the first non-empty entry
    if "," in value:
        first_part = next((part.strip() for part in value.split(",") if part.strip()), "")
        if first_part:
            value = first_part

    # Handle Workforce Identity Pool principal URIs ending in /subject/<identity>
    if "/subject/" in value:
        subject_tail = value.rsplit("/subject/", 1)[-1].strip()
        if subject_tail:
            value = subject_tail

    # Strip IAP issuer prefix (e.g., 'accounts.google.com:jane.doe@company.com'
    # or 'securetoken.google.com/proj/okta:jane.doe@company.com')
    if ":" in value:
        prefix, remainder = value.rsplit(":", 1)
        remainder = remainder.strip()
        if remainder and (
            "@" in remainder
            or "google.com" in prefix.lower()
            or "okta" in prefix.lower()
            or "iam.googleapis.com" in prefix.lower()
        ):
            value = remainder

    return value.strip()


def _extract_email_from_jwt_payload(token: str | None) -> str:
    """Extract an email or user claim from a JWT assertion payload segment."""
    raw = str(token or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    parts = raw.split(".")
    if len(parts) < 2:
        return ""
    payload_b64 = parts[1].strip()
    if not payload_b64:
        return ""
    # Restore base64url padding
    padding = "=" * (-len(payload_b64) % 4)
    try:
        decoded_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(decoded_bytes.decode("utf-8", errors="replace"))
    except Exception:
        return ""
    if not isinstance(payload, Mapping):
        return ""

    # Check standard OIDC / Okta / IAP / GCIP email claims first
    for claim_key in ("email", "upn", "preferred_username", "login"):
        candidate = clean_iap_okta_identity(str(payload.get(claim_key) or ""))
        if candidate and "@" in candidate:
            return candidate

    # Check nested GCIP / Firebase / Okta federated claims returned by IAP
    gcip_block = payload.get("gcip")
    if isinstance(gcip_block, Mapping):
        for claim_key in ("email", "upn", "preferred_username"):
            candidate = clean_iap_okta_identity(str(gcip_block.get(claim_key) or ""))
            if candidate:
                return candidate
        firebase_block = gcip_block.get("firebase")
        if isinstance(firebase_block, Mapping):
            identities = firebase_block.get("identities")
            if isinstance(identities, Mapping):
                emails = identities.get("email")
                if isinstance(emails, list) and emails:
                    candidate = clean_iap_okta_identity(str(emails[0] or ""))
                    if candidate:
                        return candidate

    firebase_top = payload.get("firebase")
    if isinstance(firebase_top, Mapping):
        identities = firebase_top.get("identities")
        if isinstance(identities, Mapping):
            emails = identities.get("email")
            if isinstance(emails, list) and emails:
                candidate = clean_iap_okta_identity(str(emails[0] or ""))
                if candidate:
                    return candidate

    # Fallback to 'email' or 'preferred_username' even if not containing '@'
    for claim_key in ("email", "preferred_username", "upn"):
        candidate = clean_iap_okta_identity(str(payload.get(claim_key) or ""))
        if candidate:
            return candidate

    # Final fallback to 'sub' only if it looks like an email address
    sub_candidate = clean_iap_okta_identity(str(payload.get("sub") or ""))
    if "@" in sub_candidate:
        return sub_candidate
    return ""


def _get_streamlit_request_headers() -> Mapping[str, Any]:
    """Safely retrieve HTTP request headers from the active Streamlit session context."""
    if st is None:
        return {}
    try:
        context = getattr(st, "context", None)
        if context is not None:
            headers = getattr(context, "headers", None)
            if isinstance(headers, Mapping):
                return headers
    except Exception:
        pass
    return {}


def detect_authenticated_user_email(
    headers: Mapping[str, Any] | None = None,
) -> str:
    """Return the authenticated collaborator email from GCP IAP / Okta headers if present.

    Order of precedence:
    1. Direct identity headers (e.g., `X-Goog-Authenticated-User-Email` from GCP IAP / Okta)
    2. Signed JWT assertions (`X-Goog-IAP-JWT-Assertion` / Okta OIDC claims)
    3. `PAAG_DEFAULT_EDITOR` environment variable (if configured)
    """
    active_headers = headers if headers is not None else _get_streamlit_request_headers()
    if active_headers:
        lower_map: dict[str, str] = {}
        for k, v in active_headers.items():
            if k is not None and v is not None:
                lower_map[str(k).strip().lower()] = str(v)

        for header_name in IDENTITY_HEADER_CANDIDATES:
            raw_val = lower_map.get(header_name)
            cleaned = clean_iap_okta_identity(raw_val)
            if cleaned:
                return cleaned

        for jwt_header in JWT_HEADER_CANDIDATES:
            raw_jwt = lower_map.get(jwt_header)
            extracted = _extract_email_from_jwt_payload(raw_jwt)
            if extracted:
                return extracted

    env_default = clean_iap_okta_identity(os.environ.get("PAAG_DEFAULT_EDITOR"))
    if env_default:
        return env_default
    return ""
