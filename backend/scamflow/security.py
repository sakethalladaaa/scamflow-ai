"""Security primitives for anonymous ownership sessions and CSRF protection."""

import hashlib
import hmac
import secrets

from fastapi import Request

SESSION_COOKIE_NAME = "scamflow_session"
CSRF_HEADER_NAME = "X-ScamFlow-CSRF"
CSRF_HEADER_VALUE = "1"
SESSION_TOKEN_BYTES = 32


def generate_session_token() -> str:
    """Generate a cryptographically random opaque browser session token."""

    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """Hash an opaque session token for persistent lookup."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_hash_matches(token: str, expected_hash: str) -> bool:
    """Compare a presented token to a stored hash in constant time."""

    return hmac.compare_digest(hash_session_token(token), expected_hash)


def request_has_valid_csrf_context(request: Request, trusted_origin: str) -> bool:
    """Require exact same-origin context plus a non-simple custom header.

    The custom header is deliberately not a secret. Its purpose is to prevent
    ordinary cross-site form submissions from performing cookie-authenticated
    mutations. CORS is not treated as the authorization mechanism.
    """

    origin = request.headers.get("origin")
    csrf_header = request.headers.get(CSRF_HEADER_NAME)

    return origin == trusted_origin and csrf_header == CSRF_HEADER_VALUE
