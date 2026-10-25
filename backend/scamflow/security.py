"""Security primitives for anonymous ownership sessions and CSRF protection."""

import base64
import hashlib
import hmac
import secrets

try:  # Argon2 is required by the production dependency set.
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
except ImportError:  # pragma: no cover - only supports dependency-free source inspection
    PasswordHasher = None  # type: ignore[assignment,misc]
    InvalidHashError = VerificationError = VerifyMismatchError = ValueError  # type: ignore[misc,assignment]
from fastapi import Request

SESSION_COOKIE_NAME = "scamflow_session"
CSRF_HEADER_NAME = "X-ScamFlow-CSRF"
CSRF_HEADER_VALUE = "1"
REVIEWER_HEADER_NAME = "X-ScamFlow-Reviewer-Token"
SESSION_TOKEN_BYTES = 32
password_hasher = PasswordHasher() if PasswordHasher is not None else None


def generate_session_token() -> str:
    """Generate a cryptographically random opaque browser session token."""

    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """Hash an opaque session token for persistent lookup."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_hash_matches(token: str, expected_hash: str) -> bool:
    """Compare a presented token to a stored hash in constant time."""

    return hmac.compare_digest(hash_session_token(token), expected_hash)


def reviewer_token_matches(presented_token: str, configured_token: str) -> bool:
    """Compare an explicit reviewer credential in constant time."""

    return bool(presented_token) and hmac.compare_digest(
        presented_token.encode("utf-8"),
        configured_token.encode("utf-8"),
    )


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    if password_hasher is not None:
        return password_hasher.hash(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + base64.urlsafe_b64encode(salt + digest).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password without exposing parser details to callers."""

    if password_hasher is not None:
        try:
            return password_hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False
    if not password_hash.startswith("scrypt$"):
        return False
    try:
        raw = base64.urlsafe_b64decode(password_hash.removeprefix("scrypt$"))
        salt, expected = raw[:16], raw[16:]
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def request_has_valid_csrf_context(request: Request, trusted_origin: str) -> bool:
    """Require exact same-origin context plus a non-simple custom header.

    The custom header is deliberately not a secret. Its purpose is to prevent
    ordinary cross-site form submissions from performing cookie-authenticated
    mutations. CORS is not treated as the authorization mechanism.
    """

    origin = request.headers.get("origin")
    csrf_header = request.headers.get(CSRF_HEADER_NAME)

    return origin == trusted_origin and csrf_header == CSRF_HEADER_VALUE
