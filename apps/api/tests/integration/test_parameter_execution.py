"""Integration tests for driver parameter bindings, escaping, and execution security (Contract C06)."""

from decimal import Decimal
import pytest
import sqlalchemy as sa

from querylens.domain.analytics import BoundParameter
from querylens.domain.query import ValidatedQuery, compute_token_fingerprint
from querylens.execution.executor import ExecutionSecurityError, SafeExecutor
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, set_engine
from querylens.sql.bindings import compile_driver_statement


@pytest.fixture(autouse=True)
def test_db():
    test_eng = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    set_engine(test_eng)
    create_metadata_tables(test_eng)
    yield test_eng
    drop_metadata_tables(test_eng)
    test_eng.dispose()


def test_compile_driver_statement_postgres_and_mysql():
    """compile_driver_statement renders pyformat and escapes literal percent signs."""
    bindings = (
        BoundParameter(name="status", scalar_type="string", value="active"),
        BoundParameter(name="min_amount", scalar_type="decimal", value=Decimal("100.50")),
    )

    # 1. PostgreSQL query containing literal % in LIKE and strftime, plus placeholders
    pg_sql = "SELECT id FROM orders WHERE status = %(status)s AND note LIKE '%special%' AND amount >= %(min_amount)s;"
    compiled_pg, params_pg = compile_driver_statement(pg_sql, "postgresql", bindings)

    assert "%%special%%" in compiled_pg
    assert "%(status)s" in compiled_pg
    assert params_pg["status"] == "active"
    assert params_pg["min_amount"] == Decimal("100.50")

    # 2. MySQL query where sqlglot uses :status
    mysql_sql = "SELECT id FROM orders WHERE status = :status AND note LIKE '%special%' AND amount >= :min_amount;"
    compiled_my, params_my = compile_driver_statement(mysql_sql, "mysql", bindings)

    assert "%%special%%" in compiled_my
    assert "%(status)s" in compiled_my
    assert "%(min_amount)s" in compiled_my
    assert params_my["status"] == "active"
    assert params_my["min_amount"] == Decimal("100.50")


def test_compile_driver_statement_empty_bindings():
    """Empty bindings returns SQL unchanged without percent escaping."""
    sql = "SELECT * FROM orders WHERE note LIKE '%special%';"
    compiled, params = compile_driver_statement(sql, "postgresql", ())
    assert compiled == sql
    assert params == {}


def test_executor_rejects_tampered_bindings_and_sql():
    """SafeExecutor verifies token fingerprint covering bindings, limits, and SQL."""
    bindings = (BoundParameter(name="p1", scalar_type="string", value="safe_val"),)
    canonical_sql = "SELECT 1 WHERE 1 = %(p1)s;"
    fp = compute_token_fingerprint(
        canonical_sql=canonical_sql,
        bindings=bindings,
        connection_id="c1",
        engine="postgresql",
        policy_version=1,
        snapshot_hash="h1",
        permitted_identifiers=(),
        max_rows=100,
    )

    valid_token = ValidatedQuery(
        connection_id="c1",
        engine="postgresql",
        policy_version=1,
        snapshot_hash="h1",
        canonical_sql=canonical_sql,
        sql_fingerprint=fp,
        permitted_identifiers=(),
        max_rows=100,
        bindings=bindings,
    )
    assert valid_token.sql_fingerprint == fp

    # 1. Tamper binding value
    tampered_bindings = (BoundParameter(name="p1", scalar_type="string", value="tampered_val"),)
    tampered_token = ValidatedQuery(
        connection_id="c1",
        engine="postgresql",
        policy_version=1,
        snapshot_hash="h1",
        canonical_sql=canonical_sql,
        sql_fingerprint=fp,  # Old fingerprint
        permitted_identifiers=(),
        max_rows=100,
        bindings=tampered_bindings,
    )
    with pytest.raises(ExecutionSecurityError, match="fingerprint mismatch"):
        SafeExecutor.execute(tampered_token)

    # 2. Tamper canonical SQL
    tampered_sql_token = ValidatedQuery(
        connection_id="c1",
        engine="postgresql",
        policy_version=1,
        snapshot_hash="h1",
        canonical_sql="SELECT 2 WHERE 1 = %(p1)s;",
        sql_fingerprint=fp,
        permitted_identifiers=(),
        max_rows=100,
        bindings=bindings,
    )
    with pytest.raises(ExecutionSecurityError, match="fingerprint mismatch"):
        SafeExecutor.execute(tampered_sql_token)


@pytest.mark.parametrize("kind", ["postgresql", "mysql"])
def test_real_driver_rendering_keeps_literal_placeholder_text(kind):
    """Driver adaptation must escape data independently of placeholder AST nodes."""
    bindings = (BoundParameter(name="p", scalar_type="string", value="' OR SLEEP(30) -- "),)
    literal = "%(p)s :p %%"
    sql = f"SELECT '{literal}' AS note, " + ("%(p)s" if kind == "postgresql" else ":p") + " AS selected"
    statement, parameters = compile_driver_statement(sql, kind, bindings)
    if kind == "mysql":
        import pymysql
        connection = pymysql.connect(defer_connect=True)
        connection.server_status = 0
        rendered = connection.cursor().mogrify(statement, parameters)
        # A placeholder-looking literal stays a single quoted data literal.
        assert f"'{literal}' AS note" in rendered
        assert "\\' OR SLEEP(30) -- " in rendered
    else:
        from psycopg import adapt
        from psycopg._queries import PostgresQuery
        query = PostgresQuery(adapt.Transformer())
        query.convert(statement, parameters)
        assert f"'{literal}' AS note" in query.query.decode()
        assert query.params == [bindings[0].value.encode()]
