"""Pipeline error classification logic (Contracts C06, C08, C11)."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlglot.errors import ParseError

from querylens.pipeline.errors import (
    AmbiguousIntentError,
    ClassifiedError,
    FanoutDetectedError,
    RepairLimitExceededError,
    RepairStalledError,
)
from querylens.sql.functions import FunctionPolicyError
from querylens.sql.identifiers import IdentifierPolicyError
from querylens.sql.limits import LimitPolicyError
from querylens.sql.parse import SQLParseError
from querylens.sql.policy import SQLPolicyViolationError


def classify_pipeline_error(
    exception: Exception,
    engine: str | None = None,
    snapshot: Any | None = None,
) -> ClassifiedError:
    """Classify exception into a typed, sanitized, bounded ClassifiedError."""
    # 1. Security & policy exceptions take precedence - NEVER repairable even if msg has keywords
    if isinstance(exception, SQLPolicyViolationError):
        return ClassifiedError(
            category="policy",
            code="POLICY_VIOLATION",
            safe_message="Query violates read-only SQL security policy",
            repairable=False,
        )

    if isinstance(exception, (FunctionPolicyError, LimitPolicyError)):
        return ClassifiedError(
            category="policy",
            code="POLICY_VIOLATION",
            safe_message="Query violates SQL policy rules",
            repairable=False,
        )

    if isinstance(exception, PermissionError):
        return ClassifiedError(
            category="permission",
            code="PERMISSION_DENIED",
            safe_message="Insufficient privilege to perform query",
            repairable=False,
        )

    # 2. Typed pipeline domain exceptions
    if isinstance(exception, AmbiguousIntentError):
        return ClassifiedError(
            category="ambiguous_intent",
            code="AMBIGUOUS_INTENT",
            safe_message="Ambiguous query intent requires clarification",
            repairable=False,
        )

    if isinstance(exception, FanoutDetectedError):
        return ClassifiedError(
            category="fan_out",
            code="FAN_OUT_ERROR",
            safe_message="Join fan-out detected causing metric duplication",
            repairable=True,
        )

    if isinstance(exception, RepairLimitExceededError):
        return ClassifiedError(
            category="policy",
            code="MAX_ATTEMPTS_EXCEEDED",
            safe_message="Maximum repair attempts exceeded",
            repairable=False,
        )

    if isinstance(exception, RepairStalledError):
        return ClassifiedError(
            category="policy",
            code="REPAIR_STALLED",
            safe_message="Repair stalled on repeated query candidate or consecutive error",
            repairable=False,
        )

    # 3. Typed parser and validator errors (repairable)
    if isinstance(exception, (SQLParseError, ParseError)):
        return ClassifiedError(
            category="syntax",
            code="SYNTAX_ERROR",
            safe_message="Syntax error in query",
            repairable=True,
        )

    if isinstance(exception, IdentifierPolicyError):
        hints: list[str] = []
        if snapshot and hasattr(snapshot, "tables"):
            for t in snapshot.tables:
                hints.append(t.name)
                for col in t.columns:
                    hints.append(f"{t.name}.{col.name}")
        return ClassifiedError(
            category="unknown_identifier",
            code="UNKNOWN_IDENTIFIER",
            safe_message="Referenced table or column not found in schema",
            repairable=True,
            identifier_hints=hints[:5],
        )

    # 4. Timeout errors
    if isinstance(exception, (asyncio.TimeoutError, TimeoutError)):
        return ClassifiedError(
            category="timeout",
            code="STATEMENT_TIMEOUT",
            safe_message="Query execution timed out",
            repairable=False,
        )

    # 5. Extract driver error codes
    pgcode: str | None = None
    if hasattr(exception, "pgcode") and exception.pgcode:
        pgcode = str(exception.pgcode)
    elif hasattr(exception, "orig") and hasattr(exception.orig, "pgcode") and exception.orig.pgcode:
        pgcode = str(exception.orig.pgcode)
    elif hasattr(exception, "diag") and hasattr(exception.diag, "sqlstate") and exception.diag.sqlstate:
        pgcode = str(exception.diag.sqlstate)

    if pgcode:
        return _classify_pg_code(pgcode, snapshot)

    errno: int | None = None
    if hasattr(exception, "args") and exception.args and isinstance(exception.args[0], int):
        errno = exception.args[0]
    elif (
        hasattr(exception, "orig")
        and hasattr(exception.orig, "args")
        and exception.orig.args
        and isinstance(exception.orig.args[0], int)
    ):
        errno = exception.orig.args[0]

    if errno is not None:
        return _classify_mysql_code(errno, snapshot)

    # Fallback: unknown non-repairable sanitized failure
    # Crucial: raw exception string is deliberately omitted to prevent canary leakage
    return ClassifiedError(
        category="unknown",
        code="UNKNOWN_ERROR",
        safe_message="An unexpected database error occurred",
        repairable=False,
    )


def _classify_pg_code(pgcode: str, snapshot: Any | None) -> ClassifiedError:
    hints: list[str] = []
    if pgcode == "42601":
        return ClassifiedError(
            category="syntax",
            code="SYNTAX_ERROR",
            safe_message="Syntax error in SQL statement",
            repairable=True,
        )
    if pgcode == "42703":
        if snapshot and hasattr(snapshot, "tables"):
            hints = [col.name for t in snapshot.tables.values() for col in t.columns.values()][:5]
        return ClassifiedError(
            category="unknown_identifier",
            code="UNDEFINED_COLUMN",
            safe_message="Referenced column does not exist",
            repairable=True,
            identifier_hints=hints,
        )
    if pgcode == "42P01":
        if snapshot and hasattr(snapshot, "tables"):
            hints = list(snapshot.tables.keys())[:5]
        return ClassifiedError(
            category="unknown_identifier",
            code="UNDEFINED_TABLE",
            safe_message="Referenced table does not exist",
            repairable=True,
            identifier_hints=hints,
        )
    if pgcode == "42803":
        return ClassifiedError(
            category="aggregate",
            code="GROUPING_ERROR",
            safe_message="Non-aggregated column must appear in GROUP BY clause",
            repairable=True,
        )
    if pgcode == "42883":
        return ClassifiedError(
            category="function",
            code="UNDEFINED_FUNCTION",
            safe_message="Function does not exist or is not allowed",
            repairable=False,
        )
    if pgcode == "42501":
        return ClassifiedError(
            category="permission",
            code="PERMISSION_DENIED",
            safe_message="Insufficient privilege to perform query",
            repairable=False,
        )
    if pgcode == "57014":
        return ClassifiedError(
            category="timeout",
            code="STATEMENT_TIMEOUT",
            safe_message="Query execution timed out or was cancelled",
            repairable=False,
        )
    if pgcode.startswith("08"):
        return ClassifiedError(
            category="connection",
            code="CONNECTION_ERROR",
            safe_message="Database connection failure",
            repairable=False,
        )

    return ClassifiedError(
        category="unknown",
        code=f"PG_{pgcode}",
        safe_message="Database error occurred",
        repairable=False,
    )


def _classify_mysql_code(errno: int, snapshot: Any | None) -> ClassifiedError:
    hints: list[str] = []
    if errno == 1064:
        return ClassifiedError(
            category="syntax",
            code="SYNTAX_ERROR",
            safe_message="Syntax error in SQL statement",
            repairable=True,
        )
    if errno == 1054:
        if snapshot and hasattr(snapshot, "tables"):
            hints = [col.name for t in snapshot.tables.values() for col in t.columns.values()][:5]
        return ClassifiedError(
            category="unknown_identifier",
            code="UNKNOWN_COLUMN",
            safe_message="Unknown column referenced in query",
            repairable=True,
            identifier_hints=hints,
        )
    if errno == 1146:
        if snapshot and hasattr(snapshot, "tables"):
            hints = list(snapshot.tables.keys())[:5]
        return ClassifiedError(
            category="unknown_identifier",
            code="UNKNOWN_TABLE",
            safe_message="Table does not exist",
            repairable=True,
            identifier_hints=hints,
        )
    if errno == 1055:
        return ClassifiedError(
            category="aggregate",
            code="ONLY_FULL_GROUP_BY",
            safe_message="Expression not in GROUP BY clause",
            repairable=True,
        )
    if errno == 1305:
        return ClassifiedError(
            category="function",
            code="FUNCTION_DOES_NOT_EXIST",
            safe_message="Function does not exist or is not allowed",
            repairable=False,
        )
    if errno in (1142, 1143, 1227):
        return ClassifiedError(
            category="permission",
            code="PERMISSION_DENIED",
            safe_message="Access denied for query",
            repairable=False,
        )
    if errno in (3024, 1031, 1969):
        return ClassifiedError(
            category="timeout",
            code="STATEMENT_TIMEOUT",
            safe_message="Query execution timed out",
            repairable=False,
        )
    if errno in (2002, 2003, 2006, 2013):
        return ClassifiedError(
            category="connection",
            code="CONNECTION_ERROR",
            safe_message="Database connection lost",
            repairable=False,
        )

    return ClassifiedError(
        category="unknown",
        code=f"MYSQL_{errno}",
        safe_message="Database error occurred",
        repairable=False,
    )
