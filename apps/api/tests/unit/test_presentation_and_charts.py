import pytest

from querylens.domain.analytics import RunContext
from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
from querylens.pipeline.intent import build_run_context
from querylens.pipeline.explanation import derive_presentation
from querylens.semantics.metrics import MetricDefinition, MetricDSL
from querylens.semantics.versions import SemanticContext


def snapshot():
    s = CatalogSnapshot(
        connection_id="c",
        engine="postgresql",
        tables=[
            TableMetadata(
                name="sales",
                columns=[
                    ColumnMetadata(name="amount", canonical_type="decimal", db_type="numeric"),
                    ColumnMetadata(name="day", canonical_type="date", db_type="date"),
                    ColumnMetadata(name="region", canonical_type="string", db_type="text"),
                ],
            )
        ],
    )
    s.snapshot_hash = s.compute_hash()
    return s


def context():
    return RunContext(
        effective_question="Query result",
        canonical_sql_template="SELECT 1",
        snapshot_hash="a" * 64,
        policy_version=1,
        semantic_version=1,
    )


def col(name, kind):
    return {"name": name, "type": kind, "db_type": kind}


def presentation(columns, rows, **kwargs):
    return derive_presentation(columns, rows, context(), "natural_language", kwargs.pop("truncated", False), **kwargs)


def test_exact_kpi_and_manual_neutral_meaning():
    p = derive_presentation([col("total", "decimal")], [{"total": "123.4500"}], context(), "manual_sql", False)
    assert p.chart_type == "single_value"
    assert p.value == "123.4500"
    assert p.title == "Query result"
    assert "123.4500" in p.explanation
    assert presentation([col("n", "integer")], [{"n": "0"}]).chart_type == "single_value"
    assert presentation([col("n", "integer")], [{"n": "9007199254740993"}]).value == "9007199254740993"


@pytest.mark.parametrize(
    "columns,rows",
    [
        ([col("n", "integer")], []),
        ([col("n", "integer")], [{"n": None}]),
        ([col("x", "string"), col("n", "integer")], [{"x": str(i), "n": "1"} for i in range(51)]),
        ([col("x", "string"), col("n", "integer")], [{"x": "a", "n": "1"}, {"x": "a", "n": "2"}]),
        ([col("x", "string"), col("n", "integer")], [{"x": "a", "n": "9007199254740992"}]),
        ([col("x", "string"), col("n", "decimal")], [{"x": "a", "n": "0.10000000000000001"}]),
        ([col("x", "string"), col("n", "decimal")], [{"x": "a", "n": "1e400"}]),
        ([col("x", "string"), col("n", "integer")], [{"x": "", "n": "1"}]),
        ([col("x", "string"), col("n", "integer")], [{"x": "a", "n": None}]),
        ([col("a", "integer"), col("b", "integer"), col("c", "integer")], [{"a": "1", "b": "2", "c": "3"}]),
    ],
)
def test_uncertain_shapes_use_table(columns, rows):
    assert presentation(columns, rows).chart_type == "table"


def test_temporal_sort_does_not_change_table_and_truncation_visible():
    rows = [{"day": "2026-11-02", "n": "2"}, {"day": "2026-11-01", "n": "1"}]
    p = presentation([col("day", "date"), col("n", "integer")], rows, truncated=True)
    assert p.chart_type == "line" and p.plot_row_order == (1, 0)
    assert rows[0]["day"] == "2026-11-02"
    assert any("truncat" in warning.lower() for warning in p.warnings)


def test_context_exact_metric_filters_and_grain_and_ast_references():
    s = snapshot()
    dsl = MetricDSL(
        key="revenue",
        name="Revenue",
        table="public.sales",
        measure_column="amount",
        aggregation="sum",
        filters=[{"column": "region", "operator": "eq", "value": "ZA"}],
        grain=["day"],
        units="USD",
    )
    metric = MetricDefinition(
        id="m", connection_id="c", key="revenue", name="Revenue", description=None, dsl=dsl, version=2, enabled=True
    )
    semantics = SemanticContext(semantic_version=3, metrics=(metric,))
    sql = "SELECT day, SUM(amount) AS revenue FROM public.sales WHERE region='ZA' GROUP BY day"
    c = build_run_context(sql, None, "Revenue by day", "natural_language", s, semantics)
    assert [r.key for r in c.metric_references] == ["revenue"]
    assert {r.column_name for r in c.referenced_objects} >= {"day", "amount", "region"}
    assert c.applied_filters[0].value == "ZA"
    for bad_sql in [
        sql.replace("='ZA'", "='US'"),
        sql.replace("SUM(amount)", "AVG(amount)"),
        sql.replace(" GROUP BY day", ""),
        sql.replace("WHERE region='ZA'", "WHERE region='ZA' OR amount>0"),
    ]:
        assert not build_run_context(bad_sql, None, "revenue", "natural_language", s, semantics).metric_references
    manual = build_run_context(
        "SELECT SUM(amount) AS n FROM public.sales", None, "Original revenue question", "manual_sql", s, semantics
    )
    assert "Original revenue question" not in manual.effective_question


def test_mixed_units_fall_back():
    assert (
        presentation(
            [col("category", "string"), col("amount", "decimal")],
            [{"category": "x", "amount": "1"}],
            units=("USD", "EUR"),
        ).chart_type
        == "table"
    )


@pytest.mark.parametrize(
    "operator,value,predicate",
    [
        ("gt", 12.5, "amount > 12.5"),
        ("lt", -12.5, "amount < -12.5"),
        ("in", [1, 2.5], "amount IN (1, 2.5)"),
        ("not_in", [1, 2.5], "amount NOT IN (1, 2.5)"),
        ("is_null", None, "amount IS NULL"),
        ("is_not_null", None, "amount IS NOT NULL"),
    ],
)
def test_metric_numeric_and_null_filters(operator, value, predicate):
    s = snapshot()
    dsl = MetricDSL(
        key="total",
        name="Total",
        table="public.sales",
        measure_column="amount",
        aggregation="sum",
        filters=[{"column": "amount", "operator": operator, "value": value}],
    )
    m = MetricDefinition(
        id="m", connection_id="c", key="total", name="Total", description=None, dsl=dsl, version=1, enabled=True
    )
    sql = "SELECT SUM(amount) FROM public.sales WHERE " + predicate
    assert build_run_context(sql, None, "total", "natural_language", s, SemanticContext(metrics=(m,))).metric_references
    if operator == "gt":
        sql = sql.replace("12.5", "'12.5'")
        assert not build_run_context(
            sql, None, "total", "natural_language", s, SemanticContext(metrics=(m,))
        ).metric_references


@pytest.mark.parametrize(
    "columns,rows",
    [
        ([col("x", "date"), col("y", "integer")], [{"x": "2026-02-30", "y": "1"}]),
        (
            [col("x", "datetime"), col("y", "integer")],
            [{"x": "2026-11-01T00:00:00Z", "y": "1"}, {"x": "2026-10-31T19:00:00-05:00", "y": "2"}],
        ),
        ([col("x", "string"), col("y", "string")], [{"x": "a", "y": "1.2"}]),
        ([col("x", "string"), col("y", "decimal")], [{"x": "a", "y": "0.1"}, {"x": "b", "y": "0.10000000000000001"}]),
    ],
)
def test_temporal_and_declared_type_precision_fallback(columns, rows):
    assert presentation(columns, rows).chart_type == "table"


@pytest.mark.parametrize("negative", [False, True])
def test_metric_long_numeric_literals_remain_exact(negative):
    s = snapshot()
    value = 123456789012345678901234567890123456789
    if negative:
        value = -value
    dsl = MetricDSL(
        key="total",
        name="Total",
        table="public.sales",
        measure_column="amount",
        aggregation="sum",
        filters=[{"column": "amount", "operator": "eq", "value": value}],
    )
    m = MetricDefinition(
        id="m", connection_id="c", key="total", name="Total", description=None, dsl=dsl, version=1, enabled=True
    )
    semantics = SemanticContext(metrics=(m,))
    sql = f"SELECT SUM(amount) FROM public.sales WHERE amount = {value}"
    exact = build_run_context(sql, None, "total", "natural_language", s, semantics)
    assert exact.metric_references and exact.applied_filters[0].value == value
    different = sql.replace(str(value), str(value + 1))
    assert not build_run_context(different, None, "total", "natural_language", s, semantics).metric_references


@pytest.mark.parametrize(
    "source",
    [
        "public.sales TABLESAMPLE SYSTEM(10)",
        "ONLY public.sales",
    ],
)
def test_validated_relation_modifiers_do_not_assert_full_table_metric(source):
    from querylens.sql.policy import validate_query_artifact

    s = snapshot()
    dsl = MetricDSL(key="total", name="Total", table="public.sales", measure_column="amount", aggregation="sum")
    m = MetricDefinition(
        id="m", connection_id="c", key="total", name="Total", description=None, dsl=dsl, version=1, enabled=True
    )
    semantics = SemanticContext(metrics=(m,))
    artifact = validate_query_artifact(f"SELECT SUM(amount) FROM {source}", "c", "postgresql", s)
    result = build_run_context(artifact.template_sql, artifact.author_limit, "total", "natural_language", s, semantics)
    assert not result.metric_references
    assert "Verified metric" not in result.effective_question
    presentation = derive_presentation(
        [col("total", "decimal")], [{"total": "20"}], result, "natural_language", False, semantics=semantics
    )
    assert not presentation.verified_definitions
    assert presentation.title == "Query result"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(amount) FROM public.sales",
        "SELECT SUM(s.amount) FROM public.sales AS s",
    ],
)
def test_validated_plain_and_aliased_relations_recognize_metric(sql):
    from querylens.sql.policy import validate_query_artifact

    s = snapshot()
    dsl = MetricDSL(key="total", name="Total", table="public.sales", measure_column="amount", aggregation="sum")
    m = MetricDefinition(
        id="m", connection_id="c", key="total", name="Total", description=None, dsl=dsl, version=1, enabled=True
    )
    artifact = validate_query_artifact(sql, "c", "postgresql", s)
    result = build_run_context(
        artifact.template_sql, artifact.author_limit, "total", "natural_language", s, SemanticContext(metrics=(m,))
    )
    assert [reference.key for reference in result.metric_references] == ["total"]


def test_positional_relation_alias_columns_rejected_before_context_minting():
    from querylens.sql.identifiers import IdentifierPolicyError
    from querylens.sql.policy import validate_query_artifact

    s = snapshot()
    s.tables[0].columns.append(ColumnMetadata(name="cost", canonical_type="decimal", db_type="numeric"))
    s.snapshot_hash = s.compute_hash()
    # A positional alias could make the name "amount" refer to another physical
    # column. Visible-only metadata cannot establish the source ordinal mapping.
    sql = "SELECT SUM(s.amount) FROM public.sales AS s (cost, day, region, amount)"
    with pytest.raises(IdentifierPolicyError, match="Positional|positional|alias"):
        validate_query_artifact(sql, "c", "postgresql", s)
