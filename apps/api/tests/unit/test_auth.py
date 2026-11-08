"""Unit tests for Phase 01 authentication, Argon2id hashing, and session management (Contract C02)."""

import datetime
import time
import pytest
import sqlalchemy as sa

from querylens.auth.crypto import (
    generate_session_token,
    hash_password,
    hash_token,
    verify_password,
    verify_password_sync,
)
from querylens.auth.service import AuthService, check_rate_limit, record_login_attempt
from querylens.persistence.session import create_metadata_tables, get_engine, set_engine
from querylens.persistence.tables import metadata, sessions, users


@pytest.fixture(autouse=True)
def sqlite_engine():
    """Create in-memory SQLite database for fast isolated unit tests."""
    test_eng = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    set_engine(test_eng)
    metadata.create_all(bind=test_eng)
    yield test_eng
    metadata.drop_all(bind=test_eng)
    test_eng.dispose()


@pytest.mark.asyncio
async def test_argon2id_hashing_and_verification():
    """Argon2id produces verifiable hash and rejects incorrect passwords."""
    password = "CorrectHorseBatteryStaple123!"
    pw_hash = hash_password(password)

    assert pw_hash.startswith("$argon2id$")
    assert await verify_password(password, pw_hash) is True
    assert await verify_password("WrongPassword123!", pw_hash) is False
    # None hash invokes dummy hash check and returns False
    assert await verify_password(password, None) is False


def test_session_tokens_and_hashing():
    """Session tokens are 32 bytes base64url and SHA-256 hashed."""
    raw_token, token_hash = generate_session_token()
    assert len(raw_token) >= 40  # base64url 32 bytes
    assert len(token_hash) == 64  # SHA-256 hex string
    assert hash_token(raw_token) == token_hash


def test_session_lifecycle_and_expiry():
    """Sessions expire after idle timeout or absolute timeout."""
    service = AuthService()
    user = service.create_user("test@example.com", hash_password("pass123"), role="analyst")

    sess_id, token = service.create_session(user["id"], absolute_expiry_sec=10, max_active=2)

    # Valid session
    validated = service.validate_session(token, idle_expiry_sec=5)
    assert validated is not None
    assert validated["user_id"] == user["id"]
    assert validated["email"] == "test@example.com"

    # Idle timeout
    time.sleep(0.01)
    # Simulate idle expiry by testing with idle_expiry_sec=0
    assert service.validate_session(token, idle_expiry_sec=0) is None

    # Revocation
    sess_id2, token2 = service.create_session(user["id"])
    assert service.validate_session(token2) is not None
    assert service.revoke_session(token2) is True
    assert service.validate_session(token2) is None


def test_max_active_sessions_per_user():
    """Creating more than max_active sessions revokes the oldest session."""
    service = AuthService()
    user = service.create_user("multi@example.com", hash_password("pass123"))

    _, tok1 = service.create_session(user["id"], max_active=2)
    _, tok2 = service.create_session(user["id"], max_active=2)

    assert service.validate_session(tok1) is not None
    assert service.validate_session(tok2) is not None

    # 3rd session should revoke tok1
    _, tok3 = service.create_session(user["id"], max_active=2)
    assert service.validate_session(tok1) is None
    assert service.validate_session(tok2) is not None
    assert service.validate_session(tok3) is not None


def test_rate_limiting():
    """Rate limit triggers after 5 failed attempts per min."""
    ip = "192.168.1.100"
    account = "victim@example.com"

    # First 4 failed attempts allowed
    for _ in range(4):
        allowed, _ = check_rate_limit(ip, account, max_failed=5, max_total=10)
        assert allowed is True
        record_login_attempt(ip, account, success=False)

    # 5th attempt allowed
    allowed, _ = check_rate_limit(ip, account, max_failed=5, max_total=10)
    assert allowed is True
    record_login_attempt(ip, account, success=False)

    # 6th attempt blocked
    allowed, retry_after = check_rate_limit(ip, account, max_failed=5, max_total=10)
    assert allowed is False
    assert retry_after > 0
