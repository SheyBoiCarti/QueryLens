"""PostgreSQL dialect adapter and connection manager (Contracts C01, C03, C07)."""

from __future__ import annotations

import re
from typing import Any
import psycopg
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

from querylens.connections.network import validate_destination_address

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
            # 1. SSRF and DNS address validation (C03)
            pinned_ip = validate_destination_address(host, port)

            # 2. Connection parameters
            sslmode = "require" if tls_enabled else "disable"
            conn_kwargs: dict[str, Any] = {
                "host": host,
                "hostaddr": pinned_ip,
                "port": port,
                "dbname": database,
                "user": username,
                "password": password,
                "sslmode": sslmode,
                "connect_timeout": int(timeout_sec),
            }

            with psycopg.connect(**conn_kwargs) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version();")
                    raw_version = cur.fetchone()[0]

            # Parse major version (e.g., PostgreSQL 18.6 ...)
            match = re.search(r"PostgreSQL\s+(\d+)", raw_version)
            if not match:
                return False, raw_version, "Connected, but server does not appear to be standard PostgreSQL"

            major = int(match.group(1))
            if major not in SUPPORTED_PG_VERSIONS:
                return False, raw_version, f"Unsupported PostgreSQL version {major}. Supported: {sorted(SUPPORTED_PG_VERSIONS)}"

            return True, f"PostgreSQL {major}", "Connection verified successfully"

        except Exception as e:
            # Mask credentials from error message
            msg = str(e)
            if password and password in msg:
                msg = msg.replace(password, "[REDACTED]")
            return False, "", f"PostgreSQL connection test failed: {msg}"

    @staticmethod
    def create_pool(
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        tls_enabled: bool = True,
    ) -> Engine:
        """Create bounded SQLAlchemy engine for PostgreSQL."""
        pinned_ip = validate_destination_address(host, port)
        sslmode = "require" if tls_enabled else "disable"

        url = URL.create(
            "postgresql+psycopg",
            username=username,
            password=password,
            host=host,
            port=port,
            database=database,
        )

        return create_engine(
            url,
            connect_args={
                "hostaddr": pinned_ip,
                "sslmode": sslmode,
                "connect_timeout": 5,
            },
            pool_size=5,
            max_overflow=5,
            pool_timeout=5.0,
            pool_pre_ping=True,
        )
