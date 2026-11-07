"""SQLGlot AST parser and dialect validation (Contract C06)."""

from __future__ import annotations

import sqlglot
from sqlglot import exp

MAX_SQL_BYTES = 32768


class SQLParseError(Exception):
    """Raised when SQL parsing fails or violates AST structural constraints."""
    pass


def parse_query(sql: str, dialect: str) -> exp.Expression:
    """Parse raw SQL query into a single SQLGlot AST expression.
    
    Validates single-statement constraint and dialect compatibility.
    """
    if not sql or not sql.strip():
        raise SQLParseError("Query string is empty")

    raw_bytes = sql.encode("utf-8")
    if len(raw_bytes) > MAX_SQL_BYTES:
        raise SQLParseError(f"SQL exceeds maximum allowed length of {MAX_SQL_BYTES} bytes")

    dialect_map = {
        "postgresql": "postgres",
        "mysql": "mysql",
    }
    target_dialect = dialect_map.get(dialect, dialect)

    try:
        parsed_statements = sqlglot.parse(sql, read=target_dialect)
    except Exception as e:
        raise SQLParseError(f"Syntax error parsing SQL in {dialect} dialect: {e}") from e

    # Exclude None parsed nodes
    valid_stmts = [s for s in parsed_statements if s is not None]

    if not valid_stmts:
        raise SQLParseError("No executable statement found")

    if len(valid_stmts) > 1:
        raise SQLParseError(f"Multi-statement execution is forbidden; found {len(valid_stmts)} statements")

    return valid_stmts[0]
