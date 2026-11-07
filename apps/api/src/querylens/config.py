"""Configuration and settings models for QueryLens."""

from __future__ import annotations

import os
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application runtime settings complying with contracts C01, C02, C03, C07."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    environment: Literal["development", "production", "test"] = Field(
        default="development",
        description="Runtime environment profile",
    )

    # Server config
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)
    allowed_origins: list[str] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # Metadata Database
    metadata_database_url: str = Field(
        default="sqlite+pysqlite:///./metadata.db",
        description="SQLAlchemy database URL for metadata store",
    )

    # Auth & Sessions (C02)
    session_cookie_name: str = Field(default="querylens_session")
    session_cookie_secure: bool = Field(default=False)
    session_cookie_samesite: Literal["lax", "strict", "none"] = Field(default="lax")
    session_cookie_httponly: bool = Field(default=True)
    session_cookie_path: str = Field(default="/")
    session_absolute_expiry_sec: int = Field(default=28800)  # 8 hours
    session_idle_expiry_sec: int = Field(default=1800)  # 30 minutes
    max_active_sessions_per_user: int = Field(default=10)

    # Rate limiting
    login_rate_limit_failed_per_min: int = Field(default=5)
    login_rate_limit_total_per_min: int = Field(default=10)

    # Credential Encryption (C04)
    credential_keys_file: str | None = Field(
        default=None,
        description="Path to JSON keyring file for credential encryption",
    )
    credential_active_key_id: str | None = Field(
        default=None,
        description="Active key ID for new credential encryptions",
    )

    # Budgets & Limits (C07)
    max_request_bytes: int = Field(default=65536)
    max_question_chars: int = Field(default=4000)
    max_sql_bytes: int = Field(default=32768)
    default_max_rows: int = Field(default=100)
    max_max_rows: int = Field(default=1000)
    max_result_bytes: int = Field(default=1048576)
    max_cell_bytes: int = Field(default=65536)

    global_active_jobs: int = Field(default=4)
    per_user_active_jobs: int = Field(default=2)
    per_source_active_jobs: int = Field(default=1)
    waiting_jobs_global: int = Field(default=16)
    waiting_jobs_per_user: int = Field(default=4)

    connect_timeout_sec: float = Field(default=5.0)
    pool_acquire_timeout_sec: float = Field(default=2.0)
    statement_timeout_sec: float = Field(default=10.0)
    lock_timeout_sec: float = Field(default=1.0)
    cleanup_timeout_sec: float = Field(default=5.0)

    generation_timeout_sec: float = Field(default=15.0)
    total_run_timeout_sec: float = Field(default=30.0)
    max_input_tokens: int = Field(default=6000)
    max_output_tokens: int = Field(default=2000)
    max_cumulative_tokens: int = Field(default=16000)
    max_repairs: int = Field(default=2)

    result_cache_ttl_sec: int = Field(default=300)
    result_cache_bytes: int = Field(default=33554432)

    # LLM Settings (C08)
    llm_provider: Literal["fake", "live"] = Field(default="fake")
    llm_model: str = Field(default="gpt-4o-mini")
    llm_api_key: str | None = Field(default=None)
    llm_api_base: str | None = Field(default=None)

    # External Fixture / Source Credentials (from .env)
    postgres_host: str | None = Field(default=None)
    postgres_port: int | str | None = Field(default=None)
    postgres_user: str | None = Field(default=None)
    postgres_password: str | None = Field(default=None)
    postgres_db: str | None = Field(default=None)
    postgres_sslmode: str | None = Field(default=None)
    postgres_url: str | None = Field(default=None)

    mysql_host: str | None = Field(default=None)
    mysql_port: int | str | None = Field(default=None)
    mysql_user: str | None = Field(default=None)
    mysql_password: str | None = Field(default=None)
    mysql_db: str | None = Field(default=None)
    mysql_sslmode: str | None = Field(default=None)
    mysql_url: str | None = Field(default=None)

    def validate_for_production(self) -> None:
        """Enforce strict production constraints (C01, C02, C03, C04, C11)."""
        if self.environment == "production":
            if not self.session_cookie_secure:
                raise ValueError("session_cookie_secure must be True in production")
            if not self.session_cookie_name.startswith("__Host-"):
                raise ValueError("session_cookie_name must use __Host- prefix in production")
            if self.llm_provider == "fake":
                raise ValueError("Cannot use fake LLM provider in production")
            if not self.credential_keys_file or not self.credential_active_key_id:
                raise ValueError("Production requires credential_keys_file and credential_active_key_id")


_global_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create singleton application settings."""
    global _global_settings
    if _global_settings is None:
        _global_settings = Settings()
    return _global_settings


def set_settings(settings: Settings) -> None:
    """Override singleton settings (primarily for testing)."""
    global _global_settings
    _global_settings = settings
