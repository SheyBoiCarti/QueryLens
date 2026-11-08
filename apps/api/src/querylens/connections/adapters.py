"""Unified database adapter registry and dispatcher (Contracts C01, C03, C07)."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from querylens.connections.mysql import MySQLAdapter
from querylens.connections.postgres import PostgresAdapter


def dispatch_test_connection(
    engine_name: str,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    tls_enabled: bool = True,
    ca_cert: str | None = None,
    timeout_sec: float = 5.0,
) -> tuple[bool, str, str]:
    """Dispatch connection test to target engine adapter."""
    if engine_name == "postgresql":
        return PostgresAdapter.test_connection(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tls_enabled=tls_enabled,
            ca_cert=ca_cert,
            timeout_sec=timeout_sec,
        )
    elif engine_name == "mysql":
        return MySQLAdapter.test_connection(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tls_enabled=tls_enabled,
            ca_cert=ca_cert,
            timeout_sec=timeout_sec,
        )
    else:
        return False, "", f"Unsupported engine '{engine_name}'. Only 'postgresql' and 'mysql' are supported."


def create_engine_pool(
    engine_name: str,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    tls_enabled: bool = True,
    ca_cert: str | None = None,
) -> Engine:
    """Create bounded engine pool for target engine."""
    if engine_name == "postgresql":
        return PostgresAdapter.create_pool(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tls_enabled=tls_enabled,
            ca_cert=ca_cert,
        )
    elif engine_name == "mysql":
        return MySQLAdapter.create_pool(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tls_enabled=tls_enabled,
            ca_cert=ca_cert,
        )
    else:
        raise ValueError(f"Unsupported engine: {engine_name}")
