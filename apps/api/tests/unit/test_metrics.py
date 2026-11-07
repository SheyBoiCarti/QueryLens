"""Unit tests for Phase 06 Metric DSL, snapshot validation, and fan-out detection."""

import pytest
from pydantic import ValidationError
import sqlglot

from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
from querylens.semantics.fanout import analyze_ast_semantics
from querylens.semantics.metrics import MetricDSL, MetricFilter


@pytest.fixture
def sample_snapshot():
    t_orders = TableMetadata(
        name="orders",
        columns=[
            ColumnMetadata(name="id", canonical_type="integer", db_type="int", primary_key=True),
            ColumnMetadata(name="amount", canonical_type="decimal", db_type="decimal(10,2)"),
            ColumnMetadata(name="status", canonical_type="string", db_type="varchar(50)"),
        ],
        primary_key_columns=["id"],
    )
    snap = CatalogSnapshot(connection_id="c1", engine="postgresql", tables=[t_orders])
    snap.snapshot_hash = snap.compute_hash()
    return snap


def test_metric_dsl_validation_and_hashing(sample_snapshot):
    """MetricDSL validates key pattern and verifies against visible snapshot (Contract C10)."""
    metric = MetricDSL(
        key="gross_sales",
        name="Gross Sales",
        table="orders",
        measure_column="amount",
        aggregation="sum",
        filters=[MetricFilter(column="status", operator="eq", value="completed")],
    )
    # Validates cleanly against snapshot
    metric.validate_against_snapshot(sample_snapshot)
    assert len(metric.compute_hash()) == 64

    # Invalid key with spaces/uppercase
    with pytest.raises(ValidationError):
        MetricDSL(
            key="Gross Sales!",
            name="Gross Sales",
            table="orders",
            measure_column="amount",
            aggregation="sum",
        )

    # Reference to non-existent column
    invalid_col_metric = MetricDSL(
        key="fake_metric",
        name="Fake Metric",
        table="orders",
        measure_column="nonexistent_column",
        aggregation="sum",
    )
    with pytest.raises(ValueError, match="not found"):
        invalid_col_metric.validate_against_snapshot(sample_snapshot)


def test_fanout_detection(sample_snapshot):
    """Fanout analyzer warns when joining multiple tables with independent aggregates."""
    ast = sqlglot.parse_one(
        "SELECT d.name, SUM(e.salary), SUM(o.amount) FROM departments d JOIN employees e ON d.id = e.dept_id JOIN orders o ON d.id = o.dept_id GROUP BY d.name;",
        read="postgres",
    )
    warnings = analyze_ast_semantics(ast, sample_snapshot)
    assert len(warnings) > 0
    assert warnings[0].code == "FANOUT_RISK"
