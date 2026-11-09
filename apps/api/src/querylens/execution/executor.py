"""Unified safe SQL query execution coordinator (Contracts C06, C07)."""

from __future__ import annotations

from sqlglot import exp
import sqlalchemy as sa

from querylens.connections.crypto import decrypt_credential
from querylens.connections.registry import get_registry
from querylens.domain.query import QueryResult, ValidatedQuery, compute_token_fingerprint
from querylens.execution.cancellation import check_cancelled
from querylens.execution.mysql import execute_mysql_restricted
from querylens.execution.postgres import execute_postgres_restricted
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import connections
from querylens.schema.snapshots import get_latest_snapshot
from querylens.sql.functions import validate_functions
from querylens.sql.parse import parse_query
from querylens.sql.policy import PROHIBITED_NODES


class ExecutionSecurityError(Exception):
    """Raised when query execution capability token is invalid or stale."""

    pass


class SafeExecutor:
    """Dispatches validated queries to restricted database execution engines."""

    @staticmethod
    def execute(query: ValidatedQuery, timeout_sec: float = 10.0, query_id: str | None = None) -> QueryResult:
        """Validate capability token and execute on target engine."""
        # 1. Type validation (Contract C06: reject raw strings, dicts, forged objects)
        if not isinstance(query, ValidatedQuery):
            raise ExecutionSecurityError("Raw strings or unvalidated queries cannot be executed")
        check_cancelled(query_id)

        # 2. Fingerprint check
        expected_fp = compute_token_fingerprint(
            canonical_sql=query.canonical_sql,
            bindings=query.bindings,
            connection_id=query.connection_id,
            engine=query.engine,
            policy_version=query.policy_version,
            snapshot_hash=query.snapshot_hash,
            permitted_identifiers=query.permitted_identifiers,
            max_rows=query.max_rows,
        )
        if query.sql_fingerprint != expected_fp:
            raise ExecutionSecurityError("SQL fingerprint mismatch: canonical query has been tampered with")

        # Revalidate canonical AST before source dispatch (Contract C06)
        try:
            revalidated_ast = parse_query(query.canonical_sql, dialect=query.engine)
        except Exception as exc:
            raise ExecutionSecurityError(f"Canonical SQL cannot be parsed: {exc}") from exc

        for node_type in PROHIBITED_NODES:
            if isinstance(revalidated_ast, node_type) or revalidated_ast.find(node_type):
                raise ExecutionSecurityError(f"Prohibited SQL construct in execution token: {node_type.__name__}")

        try:
            validate_functions(revalidated_ast)
        except Exception as exc:
            raise ExecutionSecurityError(f"Function policy violation: {exc}") from exc

        ast_placeholders = {
            p.this if isinstance(p.this, str) else p.this.name
            for p in revalidated_ast.find_all(exp.Placeholder, exp.Parameter)
        }
        binding_names = {b.name for b in query.bindings}
        if ast_placeholders != binding_names:
            raise ExecutionSecurityError("Placeholders in canonical AST do not match token bindings")

        # 3. Fetch connection credentials
        with get_db_connection() as conn:
            stmt = sa.select(connections).where(connections.c.id == query.connection_id).with_for_update(read=True)
            row = conn.execute(stmt).fetchone()
            if row is None:
                raise ExecutionSecurityError("Connection associated with query token no longer exists")
            conn_dict = dict(row._mapping)

            # 4. Engine dispatch check
            if conn_dict["engine"] != query.engine:
                raise ExecutionSecurityError(
                    f"Engine mismatch: query targeted for {query.engine} on {conn_dict['engine']}"
                )
            snapshot = get_latest_snapshot(query.connection_id, conn=conn)
            if (
                conn_dict["policy_version"] != query.policy_version
                or snapshot is None
                or snapshot.snapshot_hash != query.snapshot_hash
            ):
                raise ExecutionSecurityError("Connection policy changed; regenerate the query")

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
                ca_cert=conn_dict["ca_cert"],
                tls_mode=conn_dict.get("tls_mode", "verify-full"),
            )

            # 5. Dispatch to restricted engine
            if query.engine == "postgresql":
                return execute_postgres_restricted(engine_pool, query, timeout_sec=timeout_sec, query_id=query_id)
            elif query.engine == "mysql":
                return execute_mysql_restricted(engine_pool, query, timeout_sec=timeout_sec, query_id=query_id)
            else:
                raise ExecutionSecurityError(f"Unsupported engine: {query.engine}")
