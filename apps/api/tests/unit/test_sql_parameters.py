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
    sql = "SELECT id, status FROM orders WHERE status = 'active';"
    discovered = extract_eligible_parameters(sql, catalog_snapshot, "postgresql", None)
    param_def = next(item for item in discovered if item.param_type == "category").model_copy(
        update={"allowed_values": ("active", "inactive")}
    )
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


@pytest.mark.parametrize("source", [
    "SELECT id FROM orders WHERE status = 'active' OR status = 'inactive'",
    "SELECT id FROM orders WHERE id IN (SELECT id FROM orders WHERE status = 'active')",
])
def test_forged_predicate_rejected_at_compilation(catalog_snapshot, source):
    from querylens.sql.parameters import ParameterDefinition, ParameterTarget
    forged = ParameterDefinition(
        slot_id="category_status", name="status", label="Status", param_type="category", source_type="string",
        target=ParameterTarget(predicate_path="where.0", namespace="public", table_name="orders",
                               column_name="status", db_type="varchar(50)", operator="="), default_value="active",
    )
    with pytest.raises(ParameterCompilationError):
        compile_parameterized_query(source, (forged,), {}, catalog_snapshot, "conn_1", "postgresql", 100, None,
                                    dt.datetime.now(dt.UTC))


def test_alias_discovery_preserves_physical_target(catalog_snapshot):
    defs = extract_eligible_parameters("SELECT o.id FROM public.orders o WHERE o.status = 'pending'",
                                       catalog_snapshot, "postgresql", None)
    category = next(item for item in defs if item.param_type == "category")
    assert category.target.table_name == "orders"
    artifact = compile_parameterized_query("SELECT o.id FROM public.orders o WHERE o.status = 'pending'", tuple(defs),
                                          {"status": "active"}, catalog_snapshot, "conn_1", "postgresql", 100, None,
                                          dt.datetime.now(dt.UTC))
    assert artifact.token.bindings[0].value == "active"


@pytest.mark.parametrize("start,end", [(" > ", " < "), (" >= ", " <= ")])
def test_unsupported_date_boundaries_are_not_exposed(catalog_snapshot, start, end):
    defs = extract_eligible_parameters(f"SELECT id FROM orders WHERE order_date{start}'2026-01-01' AND order_date{end}'2026-02-01'",
                                       catalog_snapshot, "postgresql", None)
    assert all(item.param_type != "date_range" for item in defs)


def test_limits_without_filters_and_limit_zero(catalog_snapshot, monkeypatch):
    from querylens.config import get_settings
    monkeypatch.setattr(get_settings(), "max_max_rows", 25)
    artifact = compile_parameterized_query("SELECT id FROM orders", (), {}, catalog_snapshot, "conn_1", "postgresql",
                                          100, None, dt.datetime.now(dt.UTC))
    assert artifact.token.max_rows == 25
    assert extract_eligible_parameters("SELECT id FROM orders LIMIT 0", catalog_snapshot, "postgresql", 0) == []
    zero = compile_parameterized_query("SELECT id FROM orders LIMIT 0", (), {}, catalog_snapshot, "conn_1", "postgresql",
                                      100, 0, dt.datetime.now(dt.UTC))
    assert "LIMIT 0" in zero.token.canonical_sql


def test_self_join_filter_targets_are_not_ambiguous(catalog_snapshot):
    definitions = extract_eligible_parameters(
        "SELECT a.id FROM orders a JOIN orders b ON a.id = b.id "
        "WHERE a.order_date >= '2026-01-01' AND b.order_date < '2026-02-01'",
        catalog_snapshot, "postgresql", None,
    )
    assert [item.param_type for item in definitions] == ["result_count"]


def test_boolean_category_uses_boolean_ast_literal(catalog_snapshot):
    catalog_snapshot.tables[0].columns.append(
        ColumnMetadata(name="active", canonical_type="boolean", db_type="boolean")
    )
    catalog_snapshot.snapshot_hash = catalog_snapshot.compute_hash()
    sql = "SELECT id FROM orders WHERE active = TRUE"
    definitions = extract_eligible_parameters(sql, catalog_snapshot, "postgresql", None)
    category = next(item for item in definitions if item.param_type == "category")
    assert category.default_value is True
    compiled = compile_parameterized_query(sql, tuple(definitions), {"active": False}, catalog_snapshot,
                                           "conn_1", "postgresql", 100, None, dt.datetime.now(dt.UTC))
    assert compiled.token.bindings[0].value is False
    ambiguous = extract_eligible_parameters("SELECT id FROM orders WHERE active = 'true'", catalog_snapshot, "mysql", None)
    assert all(item.param_type != "category" for item in ambiguous)


@pytest.mark.parametrize("predicate,name,default,path", [
    ("'pending' = status AND id = 2", "status", "pending", "where.0"),
    ("order_date = '2026-01-01' AND status = 'pending'", "status", "pending", "where.1"),
    ("status = TRUE AND id = 2", "id", 2, "where.1"),
])
def test_discovery_keeps_first_eligible_category_and_its_predicate_path(catalog_snapshot, predicate, name, default, path):
    sql = f"SELECT id FROM orders WHERE {predicate}"
    definitions = extract_eligible_parameters(sql, catalog_snapshot, "postgresql", None)
    categories = [item for item in definitions if item.param_type == "category"]
    assert len(categories) == 1
    category = categories[0]
    assert category.name == name
    assert category.default_value == default
    assert category.target.predicate_path == path

    compiled = compile_parameterized_query(
        sql, tuple(definitions), {}, catalog_snapshot, "conn_1", "postgresql", 100, None,
        dt.datetime.now(dt.UTC),
    )
    assert compiled.token.bindings[0].value == default
