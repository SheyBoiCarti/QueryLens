"""Public API Pydantic schemas (Contracts C01, C02, C08, C09)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictBaseModel(BaseModel):
    """Base model forbidding extra fields."""

    model_config = ConfigDict(extra="forbid")


# --- Auth Schemas ---


class UserResponse(StrictBaseModel):
    id: str = Field(..., description="Unique user identifier")
    email: str = Field(..., description="User email address")
    role: str = Field(..., description="User role (e.g. admin, analyst)")


class LoginRequest(StrictBaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=1000)


class LoginResponse(StrictBaseModel):
    user: UserResponse
    csrf_token: str


class CsrfResponse(StrictBaseModel):
    csrf_token: str


class StatusResponse(StrictBaseModel):
    status: str


# --- Error Schemas ---


class ErrorDetail(StrictBaseModel):
    code: str
    message: str
    request_id: str


class ErrorEnvelope(StrictBaseModel):
    error: ErrorDetail
