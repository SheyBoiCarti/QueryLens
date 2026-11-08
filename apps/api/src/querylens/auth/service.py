"""Authentication, session lifecycle, and login rate limiting service (Contract C02)."""

from __future__ import annotations

import datetime
import time
import uuid
from typing import Any
import sqlalchemy as sa
from sqlalchemy.engine import Connection

from querylens.auth.crypto import generate_session_token, hash_token
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import sessions, users

# In-memory rate limiting map with timestamps:
# (key) -> list of timestamp floats
_rate_limit_map: dict[str, list[float]] = {}


def check_rate_limit(
    ip: str,
    account_key: str,
    max_failed: int = 5,
    max_total: int = 10,
    window_sec: float = 60.0,
) -> tuple[bool, int]:
    """Check whether login request is rate-limited.

    Returns:
        (is_allowed, retry_after_sec)
    """
    now = time.time()
    cutoff = now - window_sec

    ip_total_key = f"ip_total:{ip}"
    account_fail_key = f"acct_fail:{account_key.lower().strip()}"

    # Expire all keys, including accounts/IPs that never send another request.
    for k in list(_rate_limit_map):
        if k in _rate_limit_map:
            _rate_limit_map[k] = [t for t in _rate_limit_map[k] if t > cutoff]
            if not _rate_limit_map[k]:
                del _rate_limit_map[k]

    if len(_rate_limit_map) >= 10000 and ip_total_key not in _rate_limit_map:
        return False, max(1, int(window_sec))

    # Check total attempts from IP
    total_attempts = len(_rate_limit_map.get(ip_total_key, []))
    if total_attempts >= max_total:
        oldest = _rate_limit_map[ip_total_key][0]
        retry_after = max(1, int(window_sec - (now - oldest)))
        return False, retry_after

    # Check failed attempts for account from IP
    failed_attempts = len(_rate_limit_map.get(account_fail_key, []))
    if failed_attempts >= max_failed:
        oldest = _rate_limit_map[account_fail_key][0]
        retry_after = max(1, int(window_sec - (now - oldest)))
        return False, retry_after

    return True, 0


def record_login_attempt(ip: str, account_key: str, success: bool, record_total: bool = True) -> None:
    """Record a login attempt in the rate-limiting map."""
    now = time.time()
    ip_total_key = f"ip_total:{ip}"
    if record_total:
        _rate_limit_map.setdefault(ip_total_key, []).append(now)

    if not success:
        account_fail_key = f"acct_fail:{account_key.lower().strip()}"
        _rate_limit_map.setdefault(account_fail_key, []).append(now)


class AuthService:
    """Session and authentication service."""

    def __init__(self, conn: Connection | None = None) -> None:
        self._conn = conn

    def create_user(self, email: str, password_hash: str, role: str = "analyst") -> dict[str, Any]:
        """Create a user record."""
        user_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc)
        stmt = users.insert().values(
            id=user_id,
            email=email.lower().strip(),
            password_hash=password_hash,
            role=role,
            created_at=now,
            updated_at=now,
        )
        if self._conn:
            self._conn.execute(stmt)
        else:
            with get_db_connection() as conn:
                conn.execute(stmt)

        return {"id": user_id, "email": email.lower().strip(), "role": role}

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """Fetch user by email."""
        stmt = sa.select(users).where(users.c.email == email.lower().strip())
        if self._conn:
            row = self._conn.execute(stmt).fetchone()
        else:
            with get_db_connection() as conn:
                row = conn.execute(stmt).fetchone()

        if row is None:
            return None
        return dict(row._mapping)

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Fetch user by ID."""
        stmt = sa.select(users).where(users.c.id == user_id)
        if self._conn:
            row = self._conn.execute(stmt).fetchone()
        else:
            with get_db_connection() as conn:
                row = conn.execute(stmt).fetchone()

        if row is None:
            return None
        return dict(row._mapping)

    def create_session(
        self,
        user_id: str,
        absolute_expiry_sec: int = 28800,
        max_active: int = 10,
    ) -> tuple[str, str]:
        """Create a new session, enforcing max_active per user.

        Returns:
            (session_id, raw_token)
        """
        raw_token, token_hash = generate_session_token()
        session_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(seconds=absolute_expiry_sec)

        def _execute(conn: Connection) -> None:
            # Enforce max active sessions: revoke oldest active sessions if count >= max_active
            active_stmt = (
                sa.select(sessions.c.id)
                .where(
                    sessions.c.user_id == user_id,
                    sessions.c.revoked_at.is_(None),
                    sessions.c.expires_at > now,
                )
                .order_by(sessions.c.created_at.asc())
            )
            active_rows = conn.execute(active_stmt).fetchall()
            if len(active_rows) >= max_active:
                to_revoke = active_rows[: len(active_rows) - max_active + 1]
                revoke_ids = [r[0] for r in to_revoke]
                conn.execute(sessions.update().where(sessions.c.id.in_(revoke_ids)).values(revoked_at=now))

            # Insert new session
            conn.execute(
                sessions.insert().values(
                    id=session_id,
                    user_id=user_id,
                    token_hash=token_hash,
                    created_at=now,
                    last_seen_at=now,
                    expires_at=expires_at,
                    revoked_at=None,
                )
            )

        if self._conn:
            _execute(self._conn)
        else:
            with get_db_connection() as conn:
                _execute(conn)

        return session_id, raw_token

    def validate_session(
        self,
        raw_token: str,
        idle_expiry_sec: int = 1800,
    ) -> dict[str, Any] | None:
        """Validate token hash, absolute expiry, idle expiry, and return (user, session)."""
        if not raw_token or not raw_token.strip():
            return None

        token_hash = hash_token(raw_token)
        now = datetime.datetime.now(datetime.timezone.utc)

        stmt = (
            sa.select(
                sessions.c.id.label("session_id"),
                sessions.c.user_id,
                sessions.c.created_at,
                sessions.c.last_seen_at,
                sessions.c.expires_at,
                sessions.c.revoked_at,
                users.c.email,
                users.c.role,
            )
            .select_from(sessions.join(users, sessions.c.user_id == users.c.id))
            .where(sessions.c.token_hash == token_hash)
        )

        def _execute(conn: Connection):
            row = conn.execute(stmt).fetchone()
            if row is None:
                return None
            data = dict(row._mapping)

            # Check revocation
            if data["revoked_at"] is not None:
                return None

            # Check absolute expiry
            expires_at = data["expires_at"]
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
            if expires_at <= now:
                return None

            # Check idle expiry
            last_seen = data["last_seen_at"]
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=datetime.timezone.utc)
            if (now - last_seen).total_seconds() > idle_expiry_sec:
                # Expired due to idle timeout; revoke it
                conn.execute(sessions.update().where(sessions.c.id == data["session_id"]).values(revoked_at=now))
                return None

            # Update last_seen_at
            conn.execute(sessions.update().where(sessions.c.id == data["session_id"]).values(last_seen_at=now))
            return data

        if self._conn:
            return _execute(self._conn)
        else:
            with get_db_connection() as conn:
                return _execute(conn)

    def revoke_session(self, raw_token: str) -> bool:
        """Revoke session by token."""
        token_hash = hash_token(raw_token)
        now = datetime.datetime.now(datetime.timezone.utc)
        stmt = (
            sessions.update()
            .where(sessions.c.token_hash == token_hash, sessions.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        if self._conn:
            res = self._conn.execute(stmt)
        else:
            with get_db_connection() as conn:
                res = conn.execute(stmt)
        return res.rowcount > 0

    def revoke_all_user_sessions(self, user_id: str) -> int:
        """Revoke all active sessions for a user (e.g. on password change)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        stmt = (
            sessions.update()
            .where(sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        if self._conn:
            res = self._conn.execute(stmt)
        else:
            with get_db_connection() as conn:
                res = conn.execute(stmt)
        return res.rowcount
