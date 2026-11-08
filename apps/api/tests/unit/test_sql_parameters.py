"""Unit tests for SQL parameter slots, AST compilation, and immutable tokens (Contract C06)."""

import datetime as dt
import pytest
from pydantic import ValidationError

from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
from querylens.sql.parameters import (
    DateRangeFixed,
    DateRangeInput,
    DateRangeThisMonth,
    DateRangeThisYear,
    ParameterCompilationError,
    ParameterDefinition,
    ParameterTarget,
    compile_parameterized_query,
    extract_eligible_parameters,
)


@pytest.fixture
def catalog_snapshot():
    t_orders = TableMetadata(
        name="orders",
        columns=[
            ColumnMetadata(name="id", canonical_type="integer", db_type="int", primary_key=True),
            ColumnMetadata(name="customer_id", canonical_type="integer", db_type="int"),
            ColumnMetadata(name="status", canonical_type="string", db_type="varchar(50)"),
            ColumnMetadata(name="amount", canonical_type="decimal", db_type="decimal(10,2)"),
            ColumnMetadata(name="order_date", canonical_type="date", db_type="date"),
            ColumnMetadata(name="created_at", canonical_type="datetime", db_type="timestamp"),
        ],
        primary_key_columns=["id"],
    )
    snap = CatalogSnapshot(connection_id="conn_1", engine="postgresql", tables=[t_orders])
    snap.snapshot_hash = snap.compute_hash()
    return snap


def test_date_range_input_validation():
    """DateRangeInput is a strict discriminated union rejecting extra fields and invalid ranges."""
    # Valid fixed
    dr = DateRangeFixed(mode="fixed", start_date="2026-01-01", end_date_inclusive="2026-01-31")
    assert dr.mode == "fixed"
    assert dr.start_date == "2026-01-01"

    # Reversed dates rejected
    with pytest.raises(ValidationError):
        DateRangeFixed(mode="fixed", start_date="2026-02-01", end_date_inclusive="2026-01-01")

    # Invalid calendar date rejected
    with pytest.raises(ValidationError):
        DateRangeFixed(mode="fixed", start_date="2026-02-30", end_date_inclusive="2026-03-01")

    # Valid this_year and TypeAdapter
    dy = DateRangeThisYear(mode="this_year")
    assert dy.mode == "this_year"
    dm = DateRangeThisMonth(mode="this_month")
    assert dm.mode == "this_month"
    from pydantic import TypeAdapter
    adapter = TypeAdapter(DateRangeInput)
    parsed = adapter.validate_python({"mode": "this_year"})
    assert isinstance(parsed, DateRangeThisYear)
    with pytest.raises(ValidationError):
        DateRangeThisMonth.model_validate({"mode": "this_month", "extra": 1})


def test_extract_eligible_parameters_conjunctive_where(catalog_snapshot):
    """Only unambiguous conjunctive WHERE predicates and result_count are eligible."""
    sql = "SELECT id, status, order_date FROM orders WHERE status = 'pending' AND order_date >= '2026-01-01' AND order_date < '2026-02-01' LIMIT 50;"
    defs = extract_eligible_parameters(sql, catalog_snapshot, "postgresql", author_limit=50)

    # Must contain category (status), date_range (order_date), and result_count
    types = [d.param_type for d in defs]
    assert "category" in types
    assert "date_range" in types
    assert "result_count" in types

    cat_def = next(d for d in defs if d.param_type == "category")
    assert cat_def.name == "status"
    assert cat_def.source_type == "string"
    assert cat_def.default_value == "pending"

    date_def = next(d for d in defs if d.param_type == "date_range")
    assert date_def.name == "order_date"
    assert date_def.source_type == "date"
    assert date_def.default_value == {"mode": "fixed", "start_date": "2026-01-01", "end_date_inclusive": "2026-01-31"}

    rc_def = next(d for d in defs if d.param_type == "result_count")
    assert rc_def.default_value == 50


def test_extract_rejects_or_having_and_ambiguous_predicates(catalog_snapshot):
    """OR predicates, HAVING clauses, and ambiguous predicates yield no candidate filters."""
    # OR in WHERE
    sql_or = "SELECT id, status FROM orders WHERE status = 'pending' OR status = 'shipped';"
    defs_or = extract_eligible_parameters(sql_or, catalog_snapshot, "postgresql", author_limit=None)
    assert len(defs_or) == 1
    assert defs_or[0].param_type == "result_count"

    # HAVING predicate
    sql_having = "SELECT status, count(id) FROM orders GROUP BY status HAVING count(id) > 5;"
    defs_having = extract_eligible_parameters(sql_having, catalog_snapshot, "postgresql", author_limit=None)
    assert len(defs_having) == 1
    assert defs_having[0].param_type == "result_count"


def test_compile_parameterized_query_values_absent_from_sql(catalog_snapshot):
    """Selected values are absent from generated SQL and present in typed driver bindings."""
    sql = "SELECT id, status FROM orders WHERE status = 'pending';"
    defs = tuple(extract_eligible_parameters(sql, catalog_snapshot, "postgresql", author_limit=None))

    selected_status = "shipped' OR '1'='1"  # Malicious-looking allowed string
    values = {"status": selected_status, "result_count": 25}
    now = dt.datetime(2026, 11, 8, 12, 0, 0, tzinfo=dt.timezone.utc)

    artifact = compile_parameterized_query(
        template_sql=sql,
        definitions=defs,
        values=values,
        snapshot=catalog_snapshot,
        connection_id="conn_1",
        engine="postgresql",
        max_rows=100,
        author_limit=None,
        now=now,
    )

    # Value must NOT appear verbatim in canonical SQL
    assert selected_status not in artifact.token.canonical_sql
    assert "%(" in artifact.token.canonical_sql or ":" in artifact.token.canonical_sql

    # Value must be in typed bindings
    binding = next(b for b in artifact.token.bindings if b.value == selected_status)
    assert binding.scalar_type == "string"
    assert binding.value == selected_status

    # Effective limit injected
    assert artifact.token.max_rows == 25


def test_compile_category_allowed_values_membership(catalog_snapshot):
    """Category values must strictly match declared allowed_values with exact types."""
    target = ParameterTarget(
        scope="root",
        predicate_path="where.0",
        namespace="public",
        table_name="orders",
        column_name="status",
        operator="=",
    )
    param_def = ParameterDefinition(
        slot_id="slot_status",
        name="status",
        label="Status",
        param_type="category",
        source_type="string",
        target=target,
        allowed_values=("active", "inactive"),
        default_value="active",
    )
    sql = "SELECT id, status FROM orders WHERE status = 'active';"
    now = dt.datetime(2026, 11, 8, 12, 0, 0, tzinfo=dt.timezone.utc)

    # Disallowed value rejected
    with pytest.raises(ParameterCompilationError, match="allowed_values"):
        compile_parameterized_query(
            template_sql=sql,
            definitions=(param_def,),
            values={"status": "deleted"},
            snapshot=catalog_snapshot,
            connection_id="conn_1",
            engine="postgresql",
            max_rows=100,
            author_limit=None,
            now=now,
        )

    # Type mismatch rejected: int 1 is not string
    with pytest.raises(ParameterCompilationError):
        compile_parameterized_query(
            template_sql=sql,
            definitions=(param_def,),
            values={"status": 1},
            snapshot=catalog_snapshot,
            connection_id="conn_1",
            engine="postgresql",
            max_rows=100,
            author_limit=None,
            now=now,
        )


def test_compile_date_range_presets_and_boundaries(catalog_snapshot):
    """Date presets resolve to UTC inclusive-start and exclusive-end boundaries."""
    sql = "SELECT id, order_date FROM orders WHERE order_date >= '2026-01-01' AND order_date < '2026-02-01';"
    defs = tuple(extract_eligible_parameters(sql, catalog_snapshot, "postgresql", author_limit=None))

    now = dt.datetime(2026, 11, 8, 12, 0, 0, tzinfo=dt.timezone.utc)

    # Test this_month preset
    artifact = compile_parameterized_query(
        template_sql=sql,
        definitions=defs,
        values={"order_date": {"mode": "this_month"}},
        snapshot=catalog_snapshot,
        connection_id="conn_1",
        engine="postgresql",
        max_rows=100,
        author_limit=None,
        now=now,
    )

    resolved_dates = artifact.resolved_parameters.resolved_dates
    assert len(resolved_dates) == 1
    assert resolved_dates[0].start == dt.date(2026, 11, 1)
    assert resolved_dates[0].end_exclusive == dt.date(2026, 12, 1)

    # Fixed date range: inclusive end becomes exclusive midnight
    artifact_fixed = compile_parameterized_query(
        template_sql=sql,
        definitions=defs,
        values={"order_date": {"mode": "fixed", "start_date": "2026-03-01", "end_date_inclusive": "2026-03-15"}},
        snapshot=catalog_snapshot,
        connection_id="conn_1",
        engine="postgresql",
        max_rows=100,
        author_limit=None,
        now=now,
    )
    resolved_fixed = artifact_fixed.resolved_parameters.resolved_dates[0]
    assert resolved_fixed.start == dt.date(2026, 3, 1)
    assert resolved_fixed.end_exclusive == dt.date(2026, 3, 16)


def test_compile_result_count_strictly_typed_and_author_capped(catalog_snapshot):
    """Result count rejects bool/strings and cannot exceed author LIMIT."""
    sql = "SELECT id FROM orders LIMIT 20;"
    defs = tuple(extract_eligible_parameters(sql, catalog_snapshot, "postgresql", author_limit=20))
    now = dt.datetime(2026, 11, 8, 12, 0, 0, tzinfo=dt.timezone.utc)

    # Bool rejected
    with pytest.raises(ParameterCompilationError, match="integer"):
        compile_parameterized_query(
            template_sql=sql,
            definitions=defs,
            values={"result_count": True},
            snapshot=catalog_snapshot,
            connection_id="conn_1",
            engine="postgresql",
            max_rows=100,
            author_limit=20,
            now=now,
        )

    # String count rejected
    with pytest.raises(ParameterCompilationError, match="integer"):
        compile_parameterized_query(
            template_sql=sql,
            definitions=defs,
            values={"result_count": "50"},
            snapshot=catalog_snapshot,
            connection_id="conn_1",
            engine="postgresql",
            max_rows=100,
            author_limit=20,
            now=now,
        )

    # Author limit cannot be raised: 50 requested, but author_limit was 20 -> token capped at 20
    artifact = compile_parameterized_query(
        template_sql=sql,
        definitions=defs,
        values={"result_count": 50},
        snapshot=catalog_snapshot,
        connection_id="conn_1",
        engine="postgresql",
        max_rows=100,
        author_limit=20,
        now=now,
    )
    assert artifact.token.max_rows == 20
    assert artifact.resolved_parameters.max_rows == 20


def test_input_mutation_does_not_affect_minted_token(catalog_snapshot):
    """Mutating the caller's values mapping after compilation does not alter token bindings."""
    sql = "SELECT id, status FROM orders WHERE status = 'pending';"
    defs = tuple(extract_eligible_parameters(sql, catalog_snapshot, "postgresql", author_limit=None))
    values = {"status": "active"}
    now = dt.datetime(2026, 11, 8, 12, 0, 0, tzinfo=dt.timezone.utc)

    artifact = compile_parameterized_query(
        template_sql=sql,
        definitions=defs,
        values=values,
        snapshot=catalog_snapshot,
        connection_id="conn_1",
        engine="postgresql",
        max_rows=100,
        author_limit=None,
        now=now,
    )

    # Mutate values dictionary
    values["status"] = "tampered"
    binding = next(b for b in artifact.token.bindings if b.scalar_type == "string")
    assert binding.value == "active"
    assert artifact.resolved_parameters.values["status"] == "active"
