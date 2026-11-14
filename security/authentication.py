"""Local authentication (bcrypt) with lockout.

This is the "secure local authentication" option from PRD 18.1. Enterprise SSO
(e.g. Microsoft Entra ID) can replace it later: AppUser.auth_provider is reserved
for that. Failure messages are intentionally generic.
"""

from __future__ import annotations

from datetime import timedelta

import bcrypt
from sqlalchemy.orm import Session

from core.config import SessionSection
from core.timeutils import ensure_utc, now_utc
from database.repositories.security_repository import SecurityRepository
from security.audit import record_activity
from security.permissions import Principal

GENERIC_FAILURE = "Invalid username or password, or the account is locked."
_BCRYPT_MAX_BYTES = 72
# Used to equalise timing when the username does not exist.
_DUMMY_HASH = bcrypt.hashpw(b"apis-mis-timing-equaliser", bcrypt.gensalt()).decode()


def validate_password_policy(password: str, min_length: int) -> list[str]:
    problems: list[str] = []
    if len(password) < min_length:
        problems.append(f"must be at least {min_length} characters")
    if len(password.encode("utf-8")) > _BCRYPT_MAX_BYTES:
        problems.append(f"must be at most {_BCRYPT_MAX_BYTES} bytes")
    classes = sum(
        [any(c.islower() for c in password), any(c.isupper() for c in password),
         any(c.isdigit() for c in password), any(not c.isalnum() for c in password)]
    )
    if classes < 3:
        problems.append("must contain at least three of: lowercase, uppercase, digit, symbol")
    return problems


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    encoded = password.encode("utf-8")
    if not password_hash or len(encoded) > _BCRYPT_MAX_BYTES:
        bcrypt.checkpw(b"x", _DUMMY_HASH.encode())
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode())
    except ValueError:
        return False


def authenticate(session: Session, username: str, password: str, policy: SessionSection) -> Principal | None:
    """Return the Principal on success, otherwise None. Audits every attempt.

    Failures are returned rather than raised so the caller's transaction commits the
    failed-attempt counter and the audit record (an exception would roll them back).
    """
    repo = SecurityRepository(session)
    user = repo.get_user_by_username(username or "")
    now = now_utc()

    if user is None:
        verify_password(password, None)  # timing equalisation
        record_activity(session, "LOGIN", "FAILED", username=(username or "")[:100], detail={"reason": "unknown_user"})
        return None

    locked_until = ensure_utc(user.locked_until)
    if not user.is_active or (locked_until and locked_until > now):
        verify_password(password, None)
        reason = "inactive" if not user.is_active else "locked"
        record_activity(session, "LOGIN", "DENIED", user_id=user.user_id, username=user.username, detail={"reason": reason})
        return None

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        detail = {"reason": "bad_password", "failed_count": user.failed_login_count}
        if user.failed_login_count >= policy.max_failed_logins:
            user.locked_until = now + timedelta(minutes=policy.lockout_minutes)
            user.failed_login_count = 0
            detail["locked"] = True
        record_activity(session, "LOGIN", "FAILED", user_id=user.user_id, username=user.username, detail=detail)
        return None

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    session.flush()
    principal = repo.load_principal(user.user_id)
    record_activity(session, "LOGIN", "SUCCESS", user_id=user.user_id, username=user.username)
    return principal
