"""PostgreSQL dialect adapter and connection manager (Contracts C01, C03, C07)."""

from __future__ import annotations

import re
import psycopg
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from querylens.connections.network import validate_destination_address
from querylens.connections.tls import postgres_ca_file
from querylens.config import get_settings

SUPPORTED_PG_VERSIONS = {16, 17, 18}


class PostgresAdapter:
    """PostgreSQL adapter using psycopg."""

    @staticmethod
    def test_connection(
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        tls_enabled: bool = True,
        ca_cert: str | None = None,
        timeout_sec: float = 5.0,
    ) -> tuple[bool, str, str]:
        """Test direct connection, server identity, and version capability check."""
        try:
            with PostgresAdapter.connect(
                host, port, database, username, password, tls_enabled, ca_cert, timeout_sec
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version();")
                    raw_version = cur.fetchone()[0]

            # Parse major version (e.g., PostgreSQL 18.6 ...)
            match = re.search(r"PostgreSQL\s+(\d+)", raw_version)
            if not match:
                return False, raw_version, "Connected, but server does not appear to be standard PostgreSQL"

            major = int(match.group(1))
            if major not in SUPPORTED_PG_VERSIONS:
                return (
                    False,
                    raw_version,
                    f"Unsupported PostgreSQL version {major}. Supported: {sorted(SUPPORTED_PG_VERSIONS)}",
                )

            return True, f"PostgreSQL {major}", "Connection verified successfully"

        except Exception as e:
            # Mask credentials from error message
            msg = str(e)
            if password and password in msg:
                msg = msg.replace(password, "[REDACTED]")
            return False, "", f"PostgreSQL connection test failed: {msg}"

    @staticmethod
    def connect(
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        tls_enabled: bool = True,
        ca_cert: str | None = None,
        timeout_sec: float | None = None,
    ):
        settings = get_settings()
        if settings.environment == "production" and not tls_enabled:
            raise ValueError("Production source connections require TLS")
        pinned_ip = validate_destination_address(host, port)
        with postgres_ca_file(ca_cert) as ca_path:
            return psycopg.connect(
                host=host,
                hostaddr=pinned_ip,
                port=port,
                dbname=database,
                user=username,
                password=password,
                sslmode="verify-full" if tls_enabled else "disable",
                sslrootcert=ca_path,
                connect_timeout=max(1, int(timeout_sec or settings.connect_timeout_sec)),
            )

    @staticmethod
    def create_pool(
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        tls_enabled: bool = True,
        ca_cert: str | None = None,
    ) -> Engine:
        settings = get_settings()
        return create_engine(
            "postgresql+psycopg://",
            creator=lambda: PostgresAdapter.connect(host, port, database, username, password, tls_enabled, ca_cert),
            pool_size=settings.per_source_active_jobs,
            max_overflow=0,
            pool_timeout=settings.pool_acquire_timeout_sec,
            pool_pre_ping=True,
        )
