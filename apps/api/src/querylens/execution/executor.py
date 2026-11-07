"""Unified safe SQL query execution coordinator (Contracts C06, C07)."""

from __future__ import annotations

import hashlib
from querylens.connections.crypto import decrypt_credential
from querylens.connections.registry import get_registry
from querylens.domain.query import QueryResult, ValidatedQuery
from querylens.execution.mysql import execute_mysql_restricted
from querylens.execution.postgres import execute_postgres_restricted
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import connections
import sqlalchemy as sa


class ExecutionSecurityError(Exception):
    """Raised when query execution capability token is invalid or stale."""
    pass


class SafeExecutor:
    """Dispatches validated queries to restricted database execution engines."""

    @staticmethod
    def execute(query: ValidatedQuery, timeout_sec: float = 10.0) -> QueryResult:
        """Validate capability token and execute on target engine."""
        # 1. Type validation (Contract C06: reject raw strings, dicts, forged objects)
        if not isinstance(query, ValidatedQuery):
            raise ExecutionSecurityError("Raw strings or unvalidated queries cannot be executed")

        # 2. Fingerprint check
        expected_fp = hashlib.sha256(query.canonical_sql.strip().encode("utf-8")).hexdigest()
        if query.sql_fingerprint != expected_fp:
            raise ExecutionSecurityError("SQL fingerprint mismatch: canonical query has been tampered with")

        # 3. Fetch connection credentials
        with get_db_connection() as conn:
            stmt = sa.select(connections).where(connections.c.id == query.connection_id)
            row = conn.execute(stmt).fetchone()
            if row is None:
                raise ExecutionSecurityError("Connection associated with query token no longer exists")
            conn_dict = dict(row._mapping)

        # 4. Engine dispatch check
        if conn_dict["engine"] != query.engine:
            raise ExecutionSecurityError(f"Engine mismatch: query targeted for {query.engine} on {conn_dict['engine']}")

        pwd = decrypt_credential(conn_dict["encrypted_password"], connection_id=query.connection_id)

        engine_pool = get_registry().get_or_create(
            connection_id=query.connection_id,
            engine_name=conn_dict["engine"],
            host=conn_dict["host"],
            port=conn_dict["port"],
            database=conn_dict["database"],
            username=conn_dict["username"],
            password=pwd,
            tls_enabled=conn_dict["tls_enabled"],
        )

        # 5. Dispatch to restricted engine
        if query.engine == "postgresql":
            return execute_postgres_restricted(engine_pool, query, timeout_sec=timeout_sec)
        elif query.engine == "mysql":
            return execute_mysql_restricted(engine_pool, query, timeout_sec=timeout_sec)
        else:
            raise ExecutionSecurityError(f"Unsupported engine: {query.engine}")
