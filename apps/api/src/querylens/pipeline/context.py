"""Question-ranked, structured schema and semantic context with hard byte bounds."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any
import sqlalchemy as sa

from querylens.domain.schema import CatalogSnapshot
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import business_metrics, few_shot_examples
from querylens.retrieval.examples import ExampleRetriever
from querylens.retrieval.join_paths import expand_join_paths
from querylens.retrieval.schema_ranker import SchemaRanker, tokenize
from querylens.semantics.metrics import MetricDSL
from querylens.sql.policy import validate_and_bound_sql

MAX_INPUT_TOKENS = 6000


@dataclass(frozen=True)
class SchemaContext:
    tables: list[Any] = field(default_factory=list)
    formatted_schema: str = ""


def estimate_tokens(text: str) -> int:
    # UTF-8 bytes are a conservative upper bound for the supported byte-based
    # tokenizers, including identifiers and multilingual questions.
    return max(1, len(text.encode("utf-8")))


def build_schema_context(snapshot: CatalogSnapshot, max_tokens: int = MAX_INPUT_TOKENS) -> str:
    header = f"TARGET DATABASE ENGINE: {snapshot.engine.upper()}\nCATALOG SNAPSHOT HASH: {snapshot.snapshot_hash}\nVISIBLE TABLES AND COLUMNS:\n"
    if estimate_tokens(header) > max_tokens:
        raise ValueError("Input budget cannot fit schema header")
    sections = [header]
    for table in snapshot.tables:
        columns = ", ".join(
            f"{col.name}:{col.canonical_type}" + ("[PK]" if col.primary_key else "") for col in table.columns
        )
        relationships = "; ".join(
            f"({','.join(fk.source_columns)})->{fk.target_table}({','.join(fk.target_columns)})"
            for fk in table.foreign_keys
        )
        block = f"TABLE {table.namespace}.{table.name}: {columns}"
        if relationships:
            block += f"; FK {relationships}"
        if estimate_tokens("\n".join(sections + [block])) <= max_tokens:
            sections.append(block)
    return "\n".join(sections)


def build_query_context(snapshot: CatalogSnapshot, question: str, max_tokens: int) -> str:
    # Reserve space for provider instructions, question, and semantic definitions.
    available = max_tokens - estimate_tokens(question) - 2200
    if available < 512:
        raise ValueError("Question leaves insufficient room for schema context")
    with get_db_connection() as conn:
        metric_rows = (
            conn.execute(
                sa.select(business_metrics.c.dsl_json)
                .where(business_metrics.c.connection_id == snapshot.connection_id, business_metrics.c.enabled.is_(True))
                .order_by(business_metrics.c.key)
                .limit(100)
            )
            .scalars()
            .all()
        )
        examples = conn.execute(
            sa.select(few_shot_examples.c.question, few_shot_examples.c.sql)
            .where(
                few_shot_examples.c.connection_id == snapshot.connection_id,
                few_shot_examples.c.verified.is_(True),
                few_shot_examples.c.dialect == snapshot.engine,
            )
            .limit(3)
        ).all()
    metrics: list[MetricDSL] = []
    for raw in metric_rows:
        try:
            metric = MetricDSL.model_validate_json(raw)
            metric.validate_against_snapshot(snapshot)
        except ValueError:
            continue  # A revoked/removed column cannot leak back through a saved metric.
        metrics.append(metric)
    question_tokens = tokenize(question)

    def metric_score(metric: MetricDSL) -> int:
        return len(question_tokens & tokenize(metric.key + " " + metric.name + " " + (metric.description or "")))

    metrics = sorted(
        (metric for metric in metrics if metric_score(metric)), key=lambda metric: (-metric_score(metric), metric.key)
    )[:3]
    ranked = SchemaRanker.rank_tables(question, snapshot, top_k=5)
    metric_tables = [
        table
        for metric in metrics
        for table in snapshot.tables
        if metric.table in (table.name, f"{table.namespace}.{table.name}")
    ]
    selected = expand_join_paths(
        list({(table.namespace, table.name): table for table in metric_tables + ranked}.values()), snapshot
    )
    subset = snapshot.model_copy(update={"tables": selected})
    context = build_schema_context(subset, max(256, int(available * 0.75)))
    additions = ["BUSINESS METRIC (apply its filters and grain): " + metric.model_dump_json() for metric in metrics]
    candidate_examples = [(row[0], row[1]) for row in examples]
    candidate_examples.extend(
        (example.question, example.sql) for example in ExampleRetriever.get_examples(snapshot.engine)
    )
    for example_question, sql in candidate_examples:
        try:
            token = validate_and_bound_sql(sql, snapshot.connection_id, snapshot.engine, subset)
        except Exception:
            continue  # Template examples referring to other schemas are never sent.
        additions.append("VERIFIED EXAMPLE: " + json.dumps({"question": example_question, "sql": token.canonical_sql}))
    for addition in additions:
        if estimate_tokens(context + "\n" + addition) <= available:
            context += "\n" + addition
    return context
