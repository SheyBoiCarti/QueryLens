"""Oracle MySQL dialect adapter and connection manager (Contracts C01, C03, C07)."""

from __future__ import annotations

from querylens.connections.models import TLSMode

import re
import socket
import ssl
import pymysql
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from querylens.connections.network import validate_destination_address
from querylens.connections.tls import certificate_failure_hint, mysql_tls_context
from querylens.config import get_settings


class VerifiedMySQLConnection(pymysql.Connection):
    """Fail before sending credentials if the server refuses required TLS."""

    pinned_ip: str

    def _read_bytes(self, num_bytes):
        if num_bytes > get_settings().max_result_bytes + 65536:
            self._force_close()
            raise pymysql.OperationalError(2013, "Source packet exceeds byte budget")
        return super()._read_bytes(num_bytes)

    def _request_authentication(self):
        from pymysql.constants import CLIENT

        if self.ssl and not self.server_capabilities & CLIENT.SSL:
            raise pymysql.OperationalError(2026, "Source server does not offer required TLS")
        return super()._request_authentication()


SUPPORTED_MYSQL_VERSIONS = {"8.0", "8.4"}


class MySQLAdapter:
    """Oracle MySQL adapter using PyMySQL."""

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
        tls_mode: TLSMode = "verify-full",
    ) -> tuple[bool, str, str]:
        """Test direct connection, verify server identity (reject MariaDB), and version capability."""
        try:
            with MySQLAdapter.connect(
                host, port, database, username, password, tls_enabled, ca_cert, timeout_sec, tls_mode=tls_mode
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version();")
                    raw_version = cur.fetchone()[0]

            # Contract C01: Reject MariaDB unconditionally by server identity
            if "mariadb" in raw_version.lower():
                return False, raw_version, "MariaDB is explicitly rejected; only Oracle MySQL is supported."

            # Check supported MySQL versions: 8.0, 8.4
            match = re.search(r"^(8\.[04])\b", raw_version)
            if not match:
                return (
                    False,
                    raw_version,
                    f"Unsupported MySQL version: {raw_version}. Supported: {sorted(SUPPORTED_MYSQL_VERSIONS)}",
                )

            matched_branch = match.group(1)
            return True, f"MySQL {matched_branch}", "Connection verified successfully"

        except Exception as e:
            msg = str(e)
            if password and password in msg:
                msg = msg.replace(password, "[REDACTED]")
            return False, "", f"MySQL connection test failed: {msg}{certificate_failure_hint(msg)}"

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
        *,
        pinned_ip: str | None = None,
        tls_context: ssl.SSLContext | None = None,
        io_timeout: float | None = None,
        tls_mode: TLSMode = "verify-full",
    ):
        settings = get_settings()
        if settings.environment == "production" and not tls_enabled:
            raise ValueError("Production source connections require TLS")
        pinned_ip = validate_destination_address(pinned_ip or host, port)
        timeout = timeout_sec or settings.connect_timeout_sec
        # Retain the DNS hostname for TLS SNI/identity, but supply an already
        # validated socket so the driver cannot resolve a different destination.
        conn = VerifiedMySQLConnection(
            host=host,
            port=port,
            user=username,
            password=password,
            database=database,
            connect_timeout=max(1, int(timeout)),
            read_timeout=io_timeout or settings.statement_timeout_sec + settings.cleanup_timeout_sec,
            write_timeout=io_timeout or settings.statement_timeout_sec + settings.cleanup_timeout_sec,
            ssl=(tls_context or mysql_tls_context(ca_cert, tls_mode)) if tls_enabled else None,
            ssl_disabled=not tls_enabled,
            defer_connect=True,
            local_infile=False,
            client_flag=0,
        )
        conn.pinned_ip = pinned_ip
        sock = socket.create_connection((pinned_ip, port), timeout=timeout)
        try:
            conn.connect(sock=sock)
        except BaseException:
            sock.close()
            raise
        return conn

    @staticmethod
    def create_pool(
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        tls_enabled: bool = True,
        ca_cert: str | None = None,
        tls_mode: TLSMode = "verify-full",
    ) -> Engine:
        settings = get_settings()
        return create_engine(
            "mysql+pymysql://",
            creator=lambda: MySQLAdapter.connect(
                host, port, database, username, password, tls_enabled, ca_cert, tls_mode=tls_mode
            ),
            pool_size=settings.per_source_active_jobs,
            max_overflow=0,
            pool_timeout=settings.pool_acquire_timeout_sec,
            pool_pre_ping=True,
        )
