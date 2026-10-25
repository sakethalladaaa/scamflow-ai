"""Account registration, password login, and role-aware session services."""

from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .database import Database
from .models import Account, OwnerSession
from .security import generate_session_token, hash_password, hash_session_token, verify_password
from .services import ServiceError
from .settings import Settings

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
LOCKOUT_SECONDS = 15 * 60
MAX_FAILED_LOGINS = 5


@dataclass(frozen=True)
class AuthResult:
    token: str
    expires_at: int
    account: Account


class LoginLimiter:
    """Small process-local limiter that protects login before account lookup.

    The account lockout fields provide persistence; this limiter adds an IP
    boundary for a single replica and avoids a database write on every abuse
    attempt. A shared edge limiter should still be configured for large scale.
    """

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        history = self._attempts[key]
        while history and history[0] <= current - 60:
            history.popleft()
        if len(history) >= limit:
            return False
        history.append(current)
        return True


login_limiter = LoginLimiter()


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if not EMAIL_RE.fullmatch(normalized):
        raise ServiceError(422, "invalid_email", "Enter a valid email address.")
    return normalized


def _new_id() -> str:
    return uuid.uuid4().hex


def _new_session(database: Database, settings: Settings, account: Account, now: int) -> AuthResult:
    token = generate_session_token()
    owner = OwnerSession(
        id=_new_id(),
        token_hash=hash_session_token(token),
        created_at=now,
        expires_at=now + settings.session_ttl_seconds,
        account_id=account.id,
    )
    with database.session_factory.begin() as session:
        session.add(owner)
    return AuthResult(token=token, expires_at=owner.expires_at, account=account)


def register_account(
    database: Database,
    settings: Settings,
    *,
    email: str,
    password: str,
    now: int,
) -> AuthResult:
    normalized = normalize_email(email)
    if len(password) < 12:
        raise ServiceError(422, "weak_password", "Password must be at least 12 characters.")
    account = Account(
        id=_new_id(),
        email=normalized,
        password_hash=hash_password(password),
        role="user",
        created_at=now,
        updated_at=now,
        active=True,
    )
    try:
        with database.session_factory.begin() as session:
            session.add(account)
    except IntegrityError as exc:
        raise ServiceError(
            409,
            "account_exists",
            "An account already exists for that email.",
        ) from exc
    return _new_session(database, settings, account, now)


def login_account(
    database: Database,
    settings: Settings,
    *,
    email: str,
    password: str,
    client_key: str,
    now: int,
) -> AuthResult:
    normalized = normalize_email(email)
    if not login_limiter.allow(client_key, settings.auth_rate_limit_per_minute):
        raise ServiceError(429, "login_rate_limited", "Too many login attempts. Try again later.")
    with database.session_factory.begin() as session:
        account = session.scalar(select(Account).where(Account.email == normalized))
        if account is None:
            raise ServiceError(401, "invalid_credentials", "Email or password is incorrect.")
        if not account.active:
            raise ServiceError(401, "invalid_credentials", "Email or password is incorrect.")
        if account.locked_until is not None and account.locked_until > now:
            raise ServiceError(429, "account_locked", "Too many failed attempts. Try again later.")
        if not verify_password(password, account.password_hash):
            account.failed_login_count += 1
            if account.failed_login_count >= MAX_FAILED_LOGINS:
                account.locked_until = now + LOCKOUT_SECONDS
                account.failed_login_count = 0
            account.updated_at = now
            raise ServiceError(401, "invalid_credentials", "Email or password is incorrect.")
        account.failed_login_count = 0
        account.locked_until = None
        account.updated_at = now
    return _new_session(database, settings, account, now)


def logout_account(database: Database, token: str | None) -> None:
    if not token:
        return
    with database.session_factory.begin() as session:
        session.execute(
            delete(OwnerSession).where(OwnerSession.token_hash == hash_session_token(token))
        )
