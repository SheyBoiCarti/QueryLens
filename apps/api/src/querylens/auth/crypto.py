"""Cryptographic utilities for password hashing and token generation (Contract C02)."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Argon2id configuration per Contract C02:
# memory_cost=65536 KiB (64 MiB), time_cost=3, parallelism=1
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

# Precomputed dummy hash for constant-time comparison against unknown users
_DUMMY_HASH = _hasher.hash("dummy_querylens_timing_mitigation_pass")


def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    return _hasher.hash(password)


def verify_password_sync(password: str, password_hash: str) -> bool:
    """Synchronously verify password against hash using Argon2id."""
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


async def verify_password(password: str, password_hash: str | None) -> bool:
    """Verify password in threadpool to keep event loop responsive; dummy check on None."""
    loop = asyncio.get_running_loop()
    if password_hash is None:
        # Constant-time mitigation: verify against dummy hash
        await loop.run_in_executor(None, verify_password_sync, password, _DUMMY_HASH)
        return False
    return await loop.run_in_executor(None, verify_password_sync, password, password_hash)


def generate_session_token() -> tuple[str, str]:
    """Generate 32-byte cryptographically random token (base64url) and its SHA-256 hash.
    
    Returns:
        (raw_token, token_hash)
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    return raw_token, token_hash


def hash_token(token: str) -> str:
    """Compute SHA-256 hash of session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    """Generate random CSRF token."""
    return secrets.token_urlsafe(32)
