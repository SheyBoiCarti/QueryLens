"""Authentication API endpoints (Contract C02)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, Header, Request, Response, status

from querylens.api.errors import (
    ForbiddenError,
    RateLimitError,
    UnauthorizedError,
)
from querylens.api.schemas import (
    CsrfResponse,
    LoginRequest,
    LoginResponse,
    StatusResponse,
    UserResponse,
)
from querylens.auth.crypto import generate_csrf_token, verify_password
from querylens.auth.dependencies import (
    get_auth_service,
    get_current_user,
    get_session_csrf,
    register_session_csrf,
    remove_session_csrf,
)
from querylens.auth.service import AuthService, check_rate_limit, record_login_attempt
from querylens.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    x_querylens_client: str | None = Header(None, alias="X-QueryLens-Client"),
    origin: str | None = Header(None, alias="Origin"),
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    """Authenticate user with email and password, returning session cookie and CSRF token."""
    client_ip = request.client.host if request.client else "127.0.0.1"

    # Enforce C02 header constraints
    if x_querylens_client != "web":
        raise ForbiddenError("Missing or invalid X-QueryLens-Client header")

    if origin and origin not in settings.allowed_origins:
        raise ForbiddenError("Unapproved request Origin")

    # Rate limiting check
    allowed, retry_after = check_rate_limit(
        client_ip,
        payload.email,
        max_failed=settings.login_rate_limit_failed_per_min,
        max_total=settings.login_rate_limit_total_per_min,
    )
    if not allowed:
        raise RateLimitError(retry_after=retry_after)

    # Fetch user
    user = auth_service.get_user_by_email(payload.email)
    password_hash = user["password_hash"] if user else None

    # Verify password (dummy check if user is None for constant-time)
    is_valid = await verify_password(payload.password, password_hash)

    # Record rate limit attempt
    record_login_attempt(client_ip, payload.email, is_valid)

    if not is_valid or not user:
        raise UnauthorizedError("Invalid email or password")

    # Revoke old session presented in cookie if any (rotation)
    old_cookie = request.cookies.get(settings.session_cookie_name)
    if old_cookie:
        auth_service.revoke_session(old_cookie)

    # Create new session
    session_id, raw_token = auth_service.create_session(
        user["id"],
        absolute_expiry_sec=settings.session_absolute_expiry_sec,
        max_active=settings.max_active_sessions_per_user,
    )

    # Generate session-bound CSRF token
    csrf_token = generate_csrf_token()
    register_session_csrf(session_id, csrf_token)

    # Set session cookie with C02 attributes
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_absolute_expiry_sec,
        secure=settings.session_cookie_secure,
        httponly=settings.session_cookie_httponly,
        samesite=settings.session_cookie_samesite,
        path=settings.session_cookie_path,
    )

    return LoginResponse(
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            role=user["role"],
        ),
        csrf_token=csrf_token,
    )


@router.post("/logout", response_model=StatusResponse)
async def logout(
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> StatusResponse:
    """Log out user, revoking the active session and clearing the cookie."""
    token = getattr(request.state, "session_token", None)
    if token:
        auth_service.revoke_session(token)

    session_id = current_user.get("session_id")
    if session_id:
        remove_session_csrf(session_id)

    response.delete_cookie(
        key=settings.session_cookie_name,
        path=settings.session_cookie_path,
    )
    return StatusResponse(status="logged_out")


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> UserResponse:
    """Return currently authenticated user information."""
    return UserResponse(
        id=current_user["user_id"],
        email=current_user["email"],
        role=current_user["role"],
    )


@router.get("/csrf", response_model=CsrfResponse)
async def get_csrf(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> CsrfResponse:
    """Return session-bound CSRF token for authenticated requests."""
    session_id = current_user.get("session_id")
    csrf_token = get_session_csrf(session_id)
    if not csrf_token:
        csrf_token = generate_csrf_token()
        register_session_csrf(session_id, csrf_token)
    return CsrfResponse(csrf_token=csrf_token)
