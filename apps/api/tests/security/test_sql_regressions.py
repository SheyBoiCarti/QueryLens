"""Security regression suite: adversarial SQL injection, bypasses, and privilege attacks (Contracts C06, C07)."""

import pytest

from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
from querylens.sql.functions import FunctionPolicyError
from querylens.sql.parse import SQLParseError
from querylens.sql.policy import SQLPolicyViolationError, validate_and_bound_sql


@pytest.fixture
def mock_snapshot():
    t = TableMetadata(
        name="accounts",
        columns=[
            ColumnMetadata(name="id", canonical_type="integer", db_type="int", primary_key=True),
            ColumnMetadata(name="balance", canonical_type="decimal", db_type="decimal(10,2)"),
        ],
        primary_key_columns=["id"],
    )
    snap = CatalogSnapshot(connection_id="c1", engine="postgresql", tables=[t])
    snap.snapshot_hash = snap.compute_hash()
    return snap


@pytest.mark.parametrize(
    "malicious_sql",
    [
        "SELECT id FROM accounts; DROP TABLE accounts; --",
        "SELECT id FROM accounts; SHUTDOWN; --",
        "WITH hacked AS (INSERT INTO accounts (id, balance) VALUES (99, 1000) RETURNING id) SELECT * FROM hacked;",
        "WITH RECURSIVE bomb AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM bomb WHERE n < 1000000) SELECT * FROM bomb;",
        "SELECT balance FROM accounts INTO OUTFILE '/var/www/html/shell.php';",
        "SELECT balance FROM accounts INTO DUMPFILE '/var/www/html/shell.php';",
        "SELECT * FROM accounts FOR UPDATE;",
        "SELECT * FROM accounts LOCK IN SHARE MODE;",
        "SELECT id FROM accounts WHERE balance = (UPDATE accounts SET balance = 0);",
        "SELECT pg_sleep(10) FROM accounts;",
        "SELECT sleep(10) FROM accounts;",
        "SELECT benchmark(10000000, MD5(1)) FROM accounts;",
        "SELECT load_file('/etc/shadow') FROM accounts;",
    ],
)
def test_adversarial_sql_patterns_blocked(malicious_sql, mock_snapshot):
    """Every defined malicious injection and bypass pattern is strictly rejected on both dialects."""
    for dialect in ["postgresql", "mysql"]:
        with pytest.raises((SQLPolicyViolationError, SQLParseError, FunctionPolicyError)):
            validate_and_bound_sql(malicious_sql, "c1", dialect, mock_snapshot)
