"""FastAPI dependencies for authentication, session verification, and CSRF (Contract C02)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any
from fastapi import Depends, Request

from querylens.api.errors import ForbiddenError
from querylens.auth.service import AuthService
from querylens.config import Settings, get_settings


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


async def get_current_user(request: Request) -> dict[str, Any]:
    """Provide the shared workspace identity; no cookie or login is required."""
    request.state.current_user = DEFAULT_DEV_USER
    return DEFAULT_DEV_USER.copy()


async def verify_csrf_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Reject foreign browser origins without requiring a session CSRF token."""
    origin = request.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        raise ForbiddenError("Unapproved request origin")
