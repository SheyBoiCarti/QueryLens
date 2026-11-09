"""Semantic retrieval preserves physical identifiers and complete definitions."""

import pytest
from pydantic import ValidationError
from querylens.domain.analytics import LabelReference
from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
from querylens.pipeline.context import build_query_context
from querylens.retrieval.schema_ranker import SchemaRanker
from querylens.semantics.metrics import MetricDSL, MetricDefinition
from querylens.semantics.versions import SemanticContext, normalize_alias


def test_normalize_alias():
    assert normalize_alias("  Ｒｅｖｅｎｕｅ\t STRAẞE  ") == "revenue strasse"


def test_synonym_validation_and_legacy_hash():
    data = dict(key="sales", name="Sales", table="orders", measure_column="amount", aggregation="sum")
    legacy = MetricDSL(**data)
    assert legacy.synonyms == []
    assert legacy.compute_hash() == MetricDSL(**data, synonyms=[]).compute_hash()
    for synonyms in ([" "], ["x" * 101], ["x"] * 21):
        with pytest.raises(ValidationError):
            MetricDSL(**data, synonyms=synonyms)


def test_complete_synonym_and_label_context(analytics_env):
    env = analytics_env
    target = TableMetadata(
        namespace="public",
        name="z_ledger",
        columns=[
            ColumnMetadata(name="amount", canonical_type="decimal", db_type="numeric"),
            ColumnMetadata(name="state", canonical_type="string", db_type="text"),
        ],
    )
    snapshot = CatalogSnapshot(
        connection_id=env.connection_id,
        engine="postgresql",
        tables=[TableMetadata(name=f"a{i}") for i in range(6)] + [target],
    )
    snapshot.snapshot_hash = snapshot.compute_hash()
    dsl = MetricDSL(
        key="settled",
        name="Settled",
        table="public.z_ledger",
        measure_column="amount",
        aggregation="sum",
        synonyms=["Takings"],
        filters=[dict(column="state", operator="eq", value="paid")],
        grain=["state"],
        units="USD",
    )
    semantic = SemanticContext(
        semantic_version=7,
        labels=(
            LabelReference(namespace="public", table_name="z_ledger", display_name="Receipts", version=2),
            LabelReference(
                namespace="public", table_name="z_ledger", column_name="amount", display_name="Proceeds", version=1
            ),
        ),
        metrics=(
            MetricDefinition(
                id="m1",
                connection_id=env.connection_id,
                key=dsl.key,
                name=dsl.name,
                description=dsl.description,
                dsl=dsl,
                version=3,
                enabled=True,
            ),
        ),
    )
    for question in ("Proceeds", "Takings"):
        assert SchemaRanker.rank_tables(question, snapshot, top_k=1, semantic_context=semantic) == [target]
    context = build_query_context(snapshot, "Takings by state", 12000, semantic_context=semantic)
    assert dsl.model_dump_json() in context
    assert "public.z_ledger" in context and "Receipts" in context and "Proceeds" in context
    assert snapshot.compute_hash() == snapshot.snapshot_hash
    # Optional labels may be omitted to retain the complete metric/schema.
    compact = build_query_context(snapshot, "Takings", 3000, semantic_context=semantic)
    assert dsl.model_dump_json() in compact
    assert len(compact.encode("utf-8")) <= 3000 - 2200 - len("Takings")
    with pytest.raises(ValueError):
        build_query_context(snapshot, "Takings", 2700, semantic_context=semantic)


def test_metric_qualified_references_preserve_visibility_and_spelling(analytics_env):
    env = analytics_env
    for field, value in (
        ("measure_column", "ID"),
        ("grain", ["secret.payroll.id"]),
        ("filters", [dict(column="secret.id", operator="eq", value=1)]),
    ):
        data = dict(key="buyers", name="Buyers", table="public.customers", measure_column="id", aggregation="count")
        data[field] = value
        with pytest.raises(ValueError):
            MetricDSL(**data).validate_against_snapshot(env.snapshot)
    MetricDSL(
        key="buyers",
        name="Buyers",
        table="public.customers",
        measure_column="id",
        aggregation="count",
        grain=["public.customers.country"],
    ).validate_against_snapshot(env.snapshot)
