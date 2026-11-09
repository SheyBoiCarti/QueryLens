"""Pydantic models for connection configuration and public responses (Contracts C01, C03, C04)."""

from __future__ import annotations

import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


TLSMode = Literal["require", "verify-ca", "verify-full"]


SupportedEngine = Literal["postgresql", "mysql"]


class VisibilityPolicy(StrictBaseModel):
    """Explicit mapping of visible tables and allowed columns."""

    allowed_tables: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Map of table names to lists of allowed column names",
    )


class ConnectionCreate(StrictBaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    engine: SupportedEngine = Field(..., description="Target engine: postgresql or mysql")
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., ge=1, le=65535)
    database: str = Field(..., min_length=1, max_length=100)
    username: str = Field(..., min_length=1, max_length=100)
    password: SecretStr = Field(..., description="Database user password")
    tls_enabled: bool = Field(default=True)
    tls_mode: TLSMode = "verify-full"
    ca_cert: str | None = Field(default=None)
    allowed_tables: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("password")
    @classmethod
    def validate_password_non_empty(cls, v: SecretStr) -> SecretStr:
        if not v.get_secret_value():
            raise ValueError("Password cannot be empty")
        return v


class ConnectionUpdate(StrictBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=100)
    username: str | None = Field(default=None, min_length=1, max_length=100)
    password: SecretStr | None = Field(default=None)
    tls_enabled: bool | None = Field(default=None)
    tls_mode: TLSMode | None = None
    ca_cert: str | None = Field(default=None)
    allowed_tables: dict[str, list[str]] | None = Field(default=None)

    @field_validator("password")
    @classmethod
    def validate_password_if_provided(cls, v: SecretStr | None) -> SecretStr | None:
        if v is not None and not v.get_secret_value():
            raise ValueError("Explicit empty password is not allowed")
        return v


class ConnectionResponse(StrictBaseModel):
    id: str
    user_id: str
    name: str
    engine: SupportedEngine
    host: str
    port: int
    database: str
    username: str
    tls_enabled: bool
    tls_mode: TLSMode = "verify-full"
    allowed_tables: dict[str, list[str]]
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ConnectionTestResponse(StrictBaseModel):
    success: bool
    server_version: str | None = None
    engine: SupportedEngine
    message: str
