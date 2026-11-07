"""Integration tests for lexical ranking, join path expansion, and few-shot retrieval (Contracts C05, C10)."""

import pytest

from querylens.domain.schema import (
    CatalogSnapshot,
    ColumnMetadata,
    ForeignKeyConstraint,
    TableMetadata,
)
from querylens.retrieval.examples import ExampleRetriever
from querylens.retrieval.join_paths import expand_join_paths
from querylens.retrieval.schema_ranker import SchemaRanker


@pytest.fixture
def multi_table_snapshot():
    customers = TableMetadata(
        name="customers",
        columns=[
            ColumnMetadata(name="id", canonical_type="integer", db_type="int", primary_key=True),
            ColumnMetadata(name="email", canonical_type="string", db_type="text"),
        ],
        primary_key_columns=["id"],
    )
    orders = TableMetadata(
        name="orders",
        columns=[
            ColumnMetadata(name="id", canonical_type="integer", db_type="int", primary_key=True),
            ColumnMetadata(name="customer_id", canonical_type="integer", db_type="int"),
            ColumnMetadata(name="total_amount", canonical_type="decimal", db_type="numeric"),
        ],
        primary_key_columns=["id"],
        foreign_keys=[
            ForeignKeyConstraint(source_columns=["customer_id"], target_table="customers", target_columns=["id"])
        ],
    )
    items = TableMetadata(
        name="items",
        columns=[
            ColumnMetadata(name="id", canonical_type="integer", db_type="int", primary_key=True),
            ColumnMetadata(name="order_id", canonical_type="integer", db_type="int"),
            ColumnMetadata(name="price", canonical_type="decimal", db_type="numeric"),
        ],
        primary_key_columns=["id"],
        foreign_keys=[
            ForeignKeyConstraint(source_columns=["order_id"], target_table="orders", target_columns=["id"])
        ],
    )
    snap = CatalogSnapshot(connection_id="c1", engine="postgresql", tables=[customers, orders, items])
    snap.snapshot_hash = snap.compute_hash()
    return snap


def test_lexical_schema_ranking(multi_table_snapshot):
    """SchemaRanker recovers customer table when asking about 'buyers' via synonym expansion."""
    ranked = SchemaRanker.rank_tables("Who are the top buyers?", multi_table_snapshot, top_k=2)
    assert len(ranked) > 0
    top_table_names = [t.name for t in ranked]
    assert "customers" in top_table_names


def test_join_path_expansion(multi_table_snapshot):
    """Bridge table 'orders' is automatically added when joining 'items' and 'customers'."""
    customers = multi_table_snapshot.tables[0]
    items = multi_table_snapshot.tables[2]

    expanded = expand_join_paths([customers, items], multi_table_snapshot)
    expanded_names = [t.name for t in expanded]
    assert "orders" in expanded_names


def test_few_shot_retrieval():
    """ExampleRetriever returns verified concept-diverse examples for dialect."""
    pg_examples = ExampleRetriever.get_examples("postgresql", limit=3)
    assert len(pg_examples) > 0
    for ex in pg_examples:
        assert ex.dialect == "postgresql"
        assert ex.sql != ""

    my_examples = ExampleRetriever.get_examples("mysql", limit=3)
    assert len(my_examples) > 0
    for ex in my_examples:
        assert ex.dialect == "mysql"
