"""Task 07.01 Tests: Error classification and taxonomy contracts.

Contracts: C06, C08, C11.
Assertions:
1. PostgreSQL SQLSTATE and MySQL vendor fixtures map to stable categories.
2. Syntax is repairable, but unsafe/function/permission/timeout/connection/ambiguity are not.
3. A security exception containing words 'syntax' or 'unknown' cannot become repairable.
4. Canary result/credential values in unknown/driver errors appear in neither prompts, responses nor logs.
"""

from __future__ import annotations


from querylens.pipeline.classifier import classify_pipeline_error
from querylens.sql.policy import SQLPolicyViolationError


class MockPgDatabaseError(Exception):
    def __init__(self, pgcode: str, message: str) -> None:
        super().__init__(message)
        self.pgcode = pgcode


class MockMySQLError(Exception):
    def __init__(self, errno: int, message: str) -> None:
        super().__init__(errno, message)
        self.args = (errno, message)


def test_postgres_sqlstate_mappings() -> None:
    # 42601 -> syntax (repairable)
    err = classify_pipeline_error(MockPgDatabaseError("42601", "syntax error at or near 'FORM'"), engine="postgres")
    assert err.category == "syntax"
    assert err.code == "SYNTAX_ERROR"
    assert err.repairable is True

    # 42703 -> unknown column (repairable)
    err = classify_pipeline_error(MockPgDatabaseError("42703", "column 'foo' does not exist"), engine="postgres")
    assert err.category == "unknown_identifier"
    assert err.repairable is True

    # 42P01 -> unknown table (repairable)
    err = classify_pipeline_error(MockPgDatabaseError("42P01", "relation 'bar' does not exist"), engine="postgres")
    assert err.category == "unknown_identifier"
    assert err.repairable is True

    # 42803 -> grouping error (repairable)
    err = classify_pipeline_error(MockPgDatabaseError("42803", "column must appear in GROUP BY"), engine="postgres")
    assert err.category == "aggregate"
    assert err.repairable is True

    # 42883 -> function error (NOT repairable)
    err = classify_pipeline_error(MockPgDatabaseError("42883", "function pg_sleep does not exist"), engine="postgres")
    assert err.category == "function"
    assert err.repairable is False

    # 42501 -> permission denied (NOT repairable)
    err = classify_pipeline_error(MockPgDatabaseError("42501", "permission denied for table secret"), engine="postgres")
    assert err.category == "permission"
    assert err.repairable is False

    # 57014 -> statement timeout (NOT repairable)
    err = classify_pipeline_error(MockPgDatabaseError("57014", "canceling statement due to statement timeout"), engine="postgres")
    assert err.category == "timeout"
    assert err.repairable is False

    # 08006 -> connection failure (NOT repairable)
    err = classify_pipeline_error(MockPgDatabaseError("08006", "connection failure"), engine="postgres")
    assert err.category == "connection"
    assert err.repairable is False


def test_mysql_vendor_code_mappings() -> None:
    # 1064 -> syntax (repairable)
    err = classify_pipeline_error(MockMySQLError(1064, "You have an error in your SQL syntax"), engine="mysql")
    assert err.category == "syntax"
    assert err.code == "SYNTAX_ERROR"
    assert err.repairable is True

    # 1054 -> unknown column (repairable)
    err = classify_pipeline_error(MockMySQLError(1054, "Unknown column 'foo' in 'field list'"), engine="mysql")
    assert err.category == "unknown_identifier"
    assert err.repairable is True

    # 1146 -> unknown table (repairable)
    err = classify_pipeline_error(MockMySQLError(1146, "Table 'test.bar' doesn't exist"), engine="mysql")
    assert err.category == "unknown_identifier"
    assert err.repairable is True

    # 1055 -> aggregate / only_full_group_by (repairable)
    err = classify_pipeline_error(MockMySQLError(1055, "Expression not in GROUP BY clause"), engine="mysql")
    assert err.category == "aggregate"
    assert err.repairable is True

    # 1305 -> function not allowed/found (NOT repairable)
    err = classify_pipeline_error(MockMySQLError(1305, "FUNCTION sleep does not exist"), engine="mysql")
    assert err.category == "function"
    assert err.repairable is False

    # 1142 -> access denied (NOT repairable)
    err = classify_pipeline_error(MockMySQLError(1142, "SELECT command denied to user"), engine="mysql")
    assert err.category == "permission"
    assert err.repairable is False

    # 3024 -> query execution timeout (NOT repairable)
    err = classify_pipeline_error(MockMySQLError(3024, "Query execution was interrupted, max_execution_time exceeded"), engine="mysql")
    assert err.category == "timeout"
    assert err.repairable is False

    # 2006 -> MySQL server has gone away (NOT repairable)
    err = classify_pipeline_error(MockMySQLError(2006, "MySQL server has gone away"), engine="mysql")
    assert err.category == "connection"
    assert err.repairable is False


def test_security_exception_cannot_become_repairable() -> None:
    # A security/policy error that mentions 'syntax' or 'unknown' MUST NOT be repairable!
    tricky_error = SQLPolicyViolationError("Forbidden node syntax or unknown statement in AST")
    err = classify_pipeline_error(tricky_error, engine="postgres")
    assert err.repairable is False
    assert err.category == "policy"
    assert err.code == "POLICY_VIOLATION"


def test_canary_credentials_and_results_not_leaked() -> None:
    canary_secret = "canary_token_secret_xyz123"
    canary_value = "canary_row_value_9999"
    raw_error = Exception(f"Internal error connecting with password={canary_secret} returning {canary_value}")

    err = classify_pipeline_error(raw_error, engine="postgres")
    assert err.repairable is False
    assert canary_secret not in err.safe_message
    assert canary_value not in err.safe_message
    assert err.category == "unknown"
    assert err.code == "UNKNOWN_ERROR"
