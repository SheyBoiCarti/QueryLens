"""FastAPI dependencies for authentication, session verification, and CSRF (Contract C02)."""

from __future__ import annotations

import hmac
from typing import Any
from fastapi import Cookie, Depends, Header, Request

from querylens.api.errors import ForbiddenError, UnauthorizedError
from querylens.auth.service import AuthService
from querylens.config import Settings, get_settings

# In-memory mapping of session_id -> csrf_token
_csrf_token_map: dict[str, str] = {}


def register_session_csrf(session_id: str, csrf_token: str) -> None:
    """Store CSRF token bound to session."""
    _csrf_token_map[session_id] = csrf_token


def get_session_csrf(session_id: str) -> str | None:
    """Retrieve CSRF token bound to session."""
    return _csrf_token_map.get(session_id)


def remove_session_csrf(session_id: str) -> None:
    """Remove CSRF token on logout/revocation."""
    _csrf_token_map.pop(session_id, None)


def get_auth_service() -> AuthService:
    """Dependency providing AuthService instance."""
    return AuthService()


async def get_current_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Extract and validate session cookie."""
    cookie_name = settings.session_cookie_name
    token = request.cookies.get(cookie_name)
    if not token:
        # Fallback for dev if standard name is used
        token = request.cookies.get("querylens_session")
        if not token:
            raise UnauthorizedError("Missing session cookie")

    user_session = auth_service.validate_session(
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
    # Check Origin header
    origin = request.headers.get("origin")
    if origin:
        if settings.environment == "development":
            # Origin must match approved origin
            if origin not in settings.allowed_origins:
                raise ForbiddenError("Unapproved request origin")
        elif settings.environment == "production":
            if origin not in settings.allowed_origins:
                raise ForbiddenError("Unapproved request origin")

    # Verify session-bound CSRF token
    session_id = current_user.get("session_id")
    expected_csrf = get_session_csrf(session_id)
    if not expected_csrf or not x_csrf_token:
        raise ForbiddenError("Missing or invalid CSRF token")

    # Constant-time comparison
    if not hmac.compare_digest(expected_csrf, x_csrf_token):
        raise ForbiddenError("Mismatched CSRF token")
