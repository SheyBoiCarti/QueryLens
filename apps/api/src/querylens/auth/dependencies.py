"""FastAPI dependencies for authentication, session verification, and CSRF (Contract C02)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any
from fastapi import Depends, Header, Request

from querylens.api.errors import ForbiddenError, UnauthorizedError
from querylens.auth.service import AuthService
from querylens.config import Settings, get_settings
from querylens.utils.workers import run_db


def derive_csrf_token(session_token: str) -> str:
    """Stable across restarts; only the HttpOnly session bearer can derive it."""
    return hmac.new(session_token.encode("utf-8"), b"querylens-csrf-v1", hashlib.sha256).hexdigest()


def get_auth_service() -> AuthService:
    """Dependency providing AuthService instance."""
    return AuthService()


DEFAULT_DEV_USER = {
    "user_id": "00000000-0000-0000-0000-000000000000",
    "session_id": "default-local-session",
    "email": "admin@querylens.local",
    "role": "admin",
}


async def get_current_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Extract and validate session cookie, or fall back to default dev user in development."""
    cookie_name = settings.session_cookie_name
    token = request.cookies.get(cookie_name)

    if not token:
        if settings.environment == "development" and settings.development_auth_bypass:
            request.state.current_user = DEFAULT_DEV_USER
            request.state.session_token = "dev-token"
            return DEFAULT_DEV_USER
        raise UnauthorizedError("Missing session cookie")

    user_session = await run_db(
        auth_service.validate_session,
        token,
        idle_expiry_sec=settings.session_idle_expiry_sec,
    )
    if not user_session:
        raise UnauthorizedError("Invalid or expired session")

    # Store raw token and user in request state
    request.state.current_user = user_session
    request.state.session_token = token
    return user_session


async def verify_csrf_token(
    request: Request,
    x_csrf_token: str | None = Header(None, alias="X-CSRF-Token"),
    current_user: dict[str, Any] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> None:
    """Verify CSRF token on authenticated mutation routes."""
    if (
        settings.environment == "development"
        and settings.development_auth_bypass
        and current_user.get("user_id") == DEFAULT_DEV_USER["user_id"]
    ):
        return

    # Check Origin header
    origin = request.headers.get("origin")
    if origin:
        if origin not in settings.allowed_origins:
            raise ForbiddenError("Unapproved request origin")

    # Verify session-bound CSRF token
    session_token = getattr(request.state, "session_token", "")
    expected_csrf = derive_csrf_token(session_token) if session_token else None
    if not expected_csrf or not x_csrf_token:
        raise ForbiddenError("Missing or invalid CSRF token")

    # Constant-time comparison
    if not hmac.compare_digest(expected_csrf, x_csrf_token):
        raise ForbiddenError("Mismatched CSRF token")
