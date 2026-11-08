"""Configuration and settings models for QueryLens."""

from __future__ import annotations

from typing import Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecurityProfileError(Exception):
    """Raised when application configuration violates security contracts."""

    pass


def validate_security_profile(settings: Settings, deployment: str = "production") -> None:
    """Validate settings against production security contracts (Contracts C01, C02, C03, C07, C11)."""
    if deployment == "production":
        # 1. Cookies & TLS
        if not settings.session_cookie_secure:
            raise SecurityProfileError("Production requires session_cookie_secure=True (HTTPS only)")
        if not settings.session_cookie_name.startswith("__Host-"):
            raise SecurityProfileError("Production requires session_cookie_name to start with '__Host-'")
        if settings.session_cookie_samesite not in ("lax", "strict"):
            raise SecurityProfileError("Production requires session_cookie_samesite='lax' or 'strict'")

        if not settings.session_cookie_httponly or settings.session_cookie_path != "/":
            raise SecurityProfileError("Production cookies require HttpOnly and Path=/")
        if settings.network_allow_loopback:
            raise SecurityProfileError("Production cannot enable loopback source access")
        if not settings.allowed_origins or any(
            "localhost" in origin or "127.0.0.1" in origin or not origin.startswith("https://")
            for origin in settings.allowed_origins
        ):
            raise SecurityProfileError("Production requires explicit HTTPS allowed_origins")
        if not settings.metadata_database_url.startswith(("postgresql", "postgres://")):
            raise SecurityProfileError("Production requires PostgreSQL metadata for single-process ownership")

        # 2. Credential encryption keyring
        if not settings.credential_keys_file or not settings.credential_active_key_id:
            raise SecurityProfileError("Production requires credential_keys_file and credential_active_key_id")

        # 3. LLM Provider credentials
        if settings.llm_provider == "fake":
            raise SecurityProfileError("Production forbids fake LLM provider")
        if settings.llm_provider != "fake" and not settings.llm_api_key:
            raise SecurityProfileError("Production requires llm_api_key for live LLM provider")

        # 4. Budgets and Limits
        if settings.max_sql_bytes > 32768:
            raise SecurityProfileError("max_sql_bytes exceeds maximum allowed hard bound (32768)")
        if settings.max_request_bytes > 65536:
            raise SecurityProfileError("max_request_bytes exceeds maximum allowed hard bound (65536)")
        if settings.session_absolute_expiry_sec > 28800:
            raise SecurityProfileError("session_absolute_expiry_sec cannot exceed 28800s (8h)")


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

    development_auth_bypass: bool = Field(default=False)

    # Server config
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)
    allowed_origins: list[str] = Field(default=["http://localhost:5173", "http://127.0.0.1:5173"])

    network_allow_loopback: bool | None = None
    network_allow_private: bool | None = None
    source_permitted_cidrs: list[str] = Field(default_factory=list)
    retention_days: int = Field(default=7, ge=1, le=365)
    maintenance_interval_sec: int = Field(default=300, ge=30)

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
    session_absolute_expiry_sec: int = Field(default=28800, ge=1)  # 8 hours
    session_idle_expiry_sec: int = Field(default=1800, ge=1)  # 30 minutes
    max_active_sessions_per_user: int = Field(default=10, ge=1)

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
    max_request_bytes: int = Field(default=65536, ge=1, le=65536)
    max_question_chars: int = Field(default=4000, ge=1, le=4000)
    max_sql_bytes: int = Field(default=32768, ge=1, le=32768)
    default_max_rows: int = Field(default=100, ge=1, le=100)
    max_max_rows: int = Field(default=1000, ge=1, le=1000)
    max_result_bytes: int = Field(default=1048576, ge=1, le=1048576)
    max_cell_bytes: int = Field(default=65536, ge=1, le=65536)

    global_active_jobs: int = Field(default=4, ge=1, le=4)
    per_user_active_jobs: int = Field(default=2, ge=1, le=2)
    per_source_active_jobs: int = Field(default=1, ge=1, le=1)
    waiting_jobs_global: int = Field(default=16, ge=1, le=16)
    waiting_jobs_per_user: int = Field(default=4, ge=1, le=4)

    connect_timeout_sec: float = Field(default=5.0, gt=0, le=5)
    pool_acquire_timeout_sec: float = Field(default=2.0, gt=0, le=2)
    statement_timeout_sec: float = Field(default=10.0, gt=0, le=10)
    lock_timeout_sec: float = Field(default=1.0, gt=0, le=1)
    cleanup_timeout_sec: float = Field(default=5.0, gt=0, le=5)

    generation_timeout_sec: float = Field(default=15.0, gt=0, le=15)
    total_run_timeout_sec: float = Field(default=30.0, gt=0, le=30)
    max_input_tokens: int = Field(default=6000, ge=1, le=6000)
    max_output_tokens: int = Field(default=2000, ge=1, le=2000)
    max_cumulative_tokens: int = Field(default=16000, ge=1, le=16000)
    max_repairs: int = Field(default=2, ge=0, le=2)

    result_cache_ttl_sec: int = Field(default=300, ge=1, le=300)
    result_cache_bytes: int = Field(default=33554432, ge=1, le=33554432)

    # LLM Settings (C08)
    llm_provider: Literal["fake", "live", "groq", "openrouter", "openai"] = Field(default="fake")
    llm_model: str = Field(default="gpt-4o-mini")
    llm_api_key: str | None = Field(default=None)
    llm_api_base: str | None = Field(default=None)

    def get_effective_llm_config(self) -> tuple[str, str, str | None]:
        """Resolve effective (api_base, model, api_key) based on provider presets."""
        provider = self.llm_provider
        api_key = self.llm_api_key

        if provider == "groq":
            api_base = self.llm_api_base or "https://api.groq.com/openai/v1"
            model = self.llm_model if self.llm_model != "gpt-4o-mini" else "openai/gpt-oss-120b"
        elif provider == "openrouter":
            api_base = self.llm_api_base or "https://openrouter.ai/api/v1"
            model = self.llm_model if self.llm_model != "gpt-4o-mini" else "meta-llama/llama-3.3-70b-instruct:free"
        elif provider in ("openai", "live"):
            api_base = self.llm_api_base or "https://api.openai.com/v1"
            model = self.llm_model
        else:
            api_base = self.llm_api_base or ""
            model = self.llm_model

        return api_base, model, api_key

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

    @model_validator(mode="after")
    def validate_budgets(self) -> Settings:
        if self.total_run_timeout_sec <= self.cleanup_timeout_sec:
            raise ValueError("total_run_timeout_sec must exceed cleanup_timeout_sec")
        if self.default_max_rows > self.max_max_rows or self.max_max_rows > 1000:
            raise ValueError("Row budgets must satisfy default_max_rows <= max_max_rows <= 1000")
        return self

    def validate_for_production(self) -> None:
        """Enforce strict production constraints (C01, C02, C03, C04, C11)."""
        validate_security_profile(self, self.environment)


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
