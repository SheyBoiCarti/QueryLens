"""Unit tests for AST parsing, SQL policies, and ValidatedQuery capability token (Contract C06)."""

import pytest

from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
from querylens.evaluation.comparison import compare_result_sets
from querylens.sql.functions import FunctionPolicyError
from querylens.sql.parse import SQLParseError, parse_query
from querylens.sql.policy import SQLPolicyViolationError, validate_and_bound_sql


@pytest.fixture
def test_snapshot():
    t1 = TableMetadata(
        name="orders",
        columns=[
            ColumnMetadata(name="id", canonical_type="integer", db_type="int", primary_key=True),
            ColumnMetadata(name="customer_id", canonical_type="integer", db_type="int"),
            ColumnMetadata(name="amount", canonical_type="decimal", db_type="decimal(10,2)"),
            ColumnMetadata(name="status", canonical_type="string", db_type="varchar(50)"),
        ],
        primary_key_columns=["id"],
    )
    snap = CatalogSnapshot(connection_id="c1", engine="postgresql", tables=[t1])
    snap.snapshot_hash = snap.compute_hash()
    return snap


def test_single_statement_enforcement():
    """Multi-statement queries are strictly prohibited (Contract C06)."""
    with pytest.raises(SQLParseError, match="Multi-statement"):
        parse_query("SELECT 1; DROP TABLE orders;", dialect="postgresql")


def test_prohibited_dml_and_ddl(test_snapshot):
    """Writes, DDL, and procedures are blocked by AST policy."""
    prohibited_queries = [
        "INSERT INTO orders (id, amount) VALUES (1, 100);",
        "UPDATE orders SET amount = 0;",
        "DELETE FROM orders WHERE id = 1;",
        "DROP TABLE orders;",
        "ALTER TABLE orders ADD COLUMN x INT;",
        "TRUNCATE TABLE orders;",
    ]
    for q in prohibited_queries:
        with pytest.raises(SQLPolicyViolationError):
            validate_and_bound_sql(q, "c1", "postgresql", test_snapshot)


def test_prohibited_locks_and_files(test_snapshot):
    """Locking reads, file exports, and variables are blocked."""
    prohibited = [
        "SELECT * FROM orders FOR UPDATE;",
        "SELECT * FROM orders FOR SHARE;",
        "SELECT * FROM orders INTO OUTFILE '/tmp/dump.txt';",
        "SELECT @my_var := 1 FROM orders;",
    ]
    for q in prohibited:
        with pytest.raises(SQLPolicyViolationError):
            validate_and_bound_sql(q, "c1", "postgresql", test_snapshot)


def test_disallowed_functions(test_snapshot):
    """Functions outside allowlist are rejected."""
    with pytest.raises(FunctionPolicyError):
        validate_and_bound_sql("SELECT pg_sleep(5) FROM orders;", "c1", "postgresql", test_snapshot)

    with pytest.raises(FunctionPolicyError):
        validate_and_bound_sql("SELECT load_file('/etc/passwd') FROM orders;", "c1", "mysql", test_snapshot)


def test_star_expansion_and_limit_bounding(test_snapshot):
    """Star projection is expanded to authorized columns and LIMIT is injected."""
    validated = validate_and_bound_sql("SELECT * FROM orders;", "c1", "postgresql", test_snapshot, max_rows=50)

    # Star was expanded
    assert "*" not in validated.canonical_sql
    assert "amount" in validated.canonical_sql
    assert "customer_id" in validated.canonical_sql
    # LIMIT injected to max_rows + 1 = 51
    assert "LIMIT 51" in validated.canonical_sql.upper()


def test_existing_smaller_limit_preserved(test_snapshot):
    """Existing smaller LIMIT is preserved and not enlarged."""
    validated = validate_and_bound_sql("SELECT id FROM orders LIMIT 10;", "c1", "postgresql", test_snapshot, max_rows=50)
    assert "LIMIT 10" in validated.canonical_sql.upper()


def test_result_comparator():
    """Result-set comparator correctly matches multiset duplicates and exact decimals."""
    actual = [{"amount": "100.50", "id": 1}, {"amount": "200.00", "id": 2}]
    expected = [{"amount": "200.0", "id": 2}, {"amount": "100.5", "id": 1}]
    # Multiset match should succeed regardless of order
    assert compare_result_sets(actual, expected, ordered=False) is True
    # Ordered match should fail
    assert compare_result_sets(actual, expected, ordered=True) is False
