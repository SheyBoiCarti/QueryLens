"""AST policy validator and ValidatedQuery minting factory (Contract C06)."""

from __future__ import annotations

import re
from sqlglot import exp
from querylens.config import get_settings
from querylens.domain.analytics import BoundParameter, ResolvedParameters
from querylens.domain.query import ValidatedArtifact, ValidatedQuery
from querylens.domain.schema import CatalogSnapshot
from querylens.sql.functions import validate_functions
from querylens.sql.identifiers import resolve_identifiers
from querylens.sql.limits import LimitPolicyError, bound_query_limits
from querylens.sql.parse import parse_query

# Forbidden AST node types (Contract C06)
PROHIBITED_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Into,
    exp.Lock,
)


class SQLPolicyViolationError(Exception):
    """Raised when query violates security policy (read-only, locks, DDL, etc.)."""

    pass


def validate_query_artifact(
    sql: str,
    connection_id: str,
    engine: str,
    snapshot: CatalogSnapshot,
    max_rows: int = 100,
    bindings: tuple[BoundParameter, ...] = (),
) -> ValidatedArtifact:
    """Validate raw SQL against AST policy and mint an immutable ValidatedQuery token."""
    settings = get_settings()
    if len(sql.encode("utf-8")) > min(32768, settings.max_sql_bytes):
        raise SQLPolicyViolationError("SQL exceeds configured UTF-8 byte budget")
    if max_rows > min(1000, settings.max_max_rows):
        raise LimitPolicyError("Row count exceeds configured budget")
    raw_lower = sql.lower()

    # Pre-parse security checks for syntax-dependent keywords across dialects
    if re.search(r"\binto\s+(outfile|dumpfile)\b", raw_lower):
        raise SQLPolicyViolationError("File exports (INTO OUTFILE/DUMPFILE) are prohibited")
    if re.search(r"\bfor\s+(update|share|no\s+key\s+update|key\s+share)\b", raw_lower):
        raise SQLPolicyViolationError("Locking reads (FOR UPDATE / FOR SHARE) are prohibited")
    if re.search(r"\block\s+in\s+share\s+mode\b", raw_lower):
        raise SQLPolicyViolationError("Locking reads (LOCK IN SHARE MODE) are prohibited")
    if re.search(r"@[a-zA-Z0-9_]+", raw_lower):
        raise SQLPolicyViolationError("User-defined variables and session parameters are prohibited")
    if re.search(r"\bwith\s+recursive\b", raw_lower):
        raise SQLPolicyViolationError("Recursive CTEs are strictly prohibited")

    # 1. Parse AST
    ast = parse_query(sql, dialect=engine)

    # 2. Root statement must be SELECT / set operation (Contract C06)
    if not isinstance(ast, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SQLPolicyViolationError(f"Statement type {type(ast).__name__} is not an authorized SELECT query")

    # 3. Check for prohibited AST nodes anywhere in tree
    for node_type in PROHIBITED_NODES:
        if isinstance(ast, node_type) or ast.find(node_type):
            raise SQLPolicyViolationError(f"Prohibited SQL construct detected: {node_type.__name__}")

    # 4. Check for recursive CTEs in AST
    if any(node.args.get("recursive") for node in ast.find_all(exp.With)):
        raise SQLPolicyViolationError("Recursive CTEs are strictly prohibited")

    ast_placeholders = {
        p.this if isinstance(p.this, str) else p.this.name
        for p in ast.find_all(exp.Placeholder, exp.Parameter)
    }
    binding_names = {b.name for b in bindings}
    if not bindings and (ast.find(exp.Placeholder) or ast.find(exp.Parameter)):
        raise SQLPolicyViolationError("Unresolved parameters are prohibited")
    if bindings and ast_placeholders != binding_names:
        raise SQLPolicyViolationError("Query placeholders do not match server bindings")

    # 7. Validate functions allowlist
    validate_functions(ast)

    # 8. Resolve identifiers against snapshot and expand stars
    permitted_identifiers = resolve_identifiers(ast, snapshot)

    # 9. Clamp/inject LIMIT (max_rows + 1)
    bounded_ast, effective_limit = bound_query_limits(ast.copy(), max_rows=max_rows)
    author_limit = int(ast.args["limit"].expression.this) if ast.args.get("limit") else None

    # 10. Generate canonical SQL (comments stripped)
    dialect_map = {"postgresql": "postgres", "mysql": "mysql"}
    target_dialect = dialect_map.get(engine, engine)
    canonical_sql = bounded_ast.sql(dialect=target_dialect, comments=False)

    template_sql = ast.sql(dialect=target_dialect, comments=False)
    if max(len(canonical_sql.encode("utf-8")), len(template_sql.encode("utf-8"))) > min(32768, settings.max_sql_bytes):
        raise SQLPolicyViolationError("Canonical SQL exceeds configured UTF-8 byte budget")

    # 11. Mint ValidatedQuery token
    token = ValidatedQuery.create(
        connection_id=connection_id,
        engine=engine,
        policy_version=snapshot.policy_version,
        snapshot_hash=snapshot.snapshot_hash,
        canonical_sql=canonical_sql,
        permitted_identifiers=permitted_identifiers,
        max_rows=max_rows,
        bindings=bindings,
    )

    return ValidatedArtifact(
        token=token,
        template_sql=template_sql,
        author_limit=author_limit,
        resolved_parameters=ResolvedParameters(bindings=bindings, max_rows=max_rows),
    )


def validate_and_bound_sql(
    sql: str,
    connection_id: str,
    engine: str,
    snapshot: CatalogSnapshot,
    max_rows: int = 100,
) -> ValidatedQuery:
    """Compatibility wrapper returning only the execution capability."""
    return validate_query_artifact(sql, connection_id, engine, snapshot, max_rows).token
