"""Oracle MySQL dialect adapter and connection manager (Contracts C01, C03, C07)."""

from __future__ import annotations

import re
import ssl
from typing import Any
import pymysql
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

from querylens.connections.network import validate_destination_address

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
    ) -> tuple[bool, str, str]:
        """Test direct connection, verify server identity (reject MariaDB), and version capability."""
        try:
            # 1. SSRF and DNS address validation (C03)
            pinned_ip = validate_destination_address(host, port)

            ssl_config = None
            if tls_enabled:
                ssl_ctx = ssl.create_default_context()
                if ca_cert:
                    ssl_ctx.load_verify_locations(cadata=ca_cert)
                else:
                    # In cloud environments with standard public CAs
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_REQUIRED
                ssl_config = {"ssl": ssl_ctx}

            conn = pymysql.connect(
                host=pinned_ip,
                port=port,
                user=username,
                password=password,
                database=database,
                connect_timeout=int(timeout_sec),
                ssl=ssl_config,
                client_flag=0,  # Disable multi-statement
                local_infile=False,  # Disable local infile (C03)
            )

            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                raw_version = cur.fetchone()[0]

            conn.close()

            # Contract C01: Reject MariaDB unconditionally by server identity
            if "mariadb" in raw_version.lower():
                return False, raw_version, "MariaDB is explicitly rejected; only Oracle MySQL is supported."

            # Check supported MySQL versions: 8.0, 8.4
            match = re.search(r"^(8\.[04])\b", raw_version)
            if not match:
                return False, raw_version, f"Unsupported MySQL version: {raw_version}. Supported: {sorted(SUPPORTED_MYSQL_VERSIONS)}"

            matched_branch = match.group(1)
            return True, f"MySQL {matched_branch}", "Connection verified successfully"

        except Exception as e:
            msg = str(e)
            if password and password in msg:
                msg = msg.replace(password, "[REDACTED]")
            return False, "", f"MySQL connection test failed: {msg}"

    @staticmethod
    def create_pool(
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        tls_enabled: bool = True,
    ) -> Engine:
        """Create bounded SQLAlchemy engine for MySQL."""
        pinned_ip = validate_destination_address(host, port)

        url = URL.create(
            "mysql+pymysql",
            username=username,
            password=password,
            host=pinned_ip,
            port=port,
            database=database,
        )

        connect_args: dict[str, Any] = {
            "connect_timeout": 5,
            "local_infile": False,
            "client_flag": 0,
        }

        if tls_enabled:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_REQUIRED
            connect_args["ssl"] = {"ssl": ssl_ctx}

        return create_engine(
            url,
            connect_args=connect_args,
            pool_size=1,
            max_overflow=0,
            pool_timeout=2.0,
            pool_pre_ping=True,
        )
