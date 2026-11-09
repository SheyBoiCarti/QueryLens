"""Semantic metadata is versioned independently of physical schema snapshots."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from fastapi import HTTPException
import sqlalchemy as sa
from sqlalchemy.engine import Connection

from querylens.api.errors import NotFoundError
from querylens.domain.analytics import LabelReference
from querylens.domain.schema import CatalogSnapshot
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import business_metrics, catalog_labels, connections
from querylens.schema.snapshots import get_latest_snapshot
from querylens.semantics.metrics import MetricDefinition, MetricDSL


def normalize_alias(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


@dataclass(frozen=True)
class SemanticContext:
    semantic_version: int = 1
    labels: tuple[LabelReference, ...] = ()
    metrics: tuple[MetricDefinition, ...] = ()


def lock_semantic_connection(conn: Connection, user_id: str, snapshot: CatalogSnapshot, *, read=False) -> dict:
    row = (
        conn.execute(
            sa.select(connections)
            .where(
                connections.c.id == snapshot.connection_id,
                connections.c.user_id == user_id,
            )
            .with_for_update(read=read)
        )
        .mappings()
        .first()
    )
    if row is None:
        raise NotFoundError("Connection not found")
    latest = get_latest_snapshot(snapshot.connection_id, conn)
    if (
        row["policy_version"] != snapshot.policy_version
        or latest is None
        or latest.snapshot_hash != snapshot.snapshot_hash
    ):
        raise HTTPException(409, "Catalog changed; reload before editing semantic definitions")
    return dict(row)


def advance_semantic_version(conn: Connection, connection_id: str) -> None:
    conn.execute(
        connections.update()
        .where(connections.c.id == connection_id)
        .values(
            semantic_version=connections.c.semantic_version + 1,
        )
    )


def label_is_visible(label, snapshot: CatalogSnapshot) -> bool:
    return any(
        table.namespace == label.namespace
        and table.name == label.table_name
        and (label.column_name is None or any(col.name == label.column_name for col in table.columns))
        for table in snapshot.tables
    )


def visible_labels(conn: Connection, snapshot: CatalogSnapshot) -> tuple[LabelReference, ...]:
    rows = conn.execute(
        sa.select(catalog_labels)
        .where(
            catalog_labels.c.connection_id == snapshot.connection_id,
        )
        .order_by(catalog_labels.c.namespace, catalog_labels.c.table_name, catalog_labels.c.column_name)
    ).mappings()
    labels = []
    for row in rows:
        label = LabelReference(**{key: row[key] for key in LabelReference.model_fields})
        if label_is_visible(label, snapshot):
            labels.append(label)
    return tuple(labels)


def visible_metrics(conn: Connection, snapshot: CatalogSnapshot, *, enabled_only=False) -> tuple[MetricDefinition, ...]:
    stmt = sa.select(business_metrics).where(business_metrics.c.connection_id == snapshot.connection_id)
    if enabled_only:
        stmt = stmt.where(business_metrics.c.enabled.is_(True))
    metrics = []
    for row in conn.execute(stmt.order_by(business_metrics.c.key)).mappings():
        try:
            dsl = MetricDSL.model_validate_json(row["dsl_json"])
            dsl.validate_against_snapshot(snapshot)
        except ValueError:
            continue
        metrics.append(
            MetricDefinition(**{key: row[key] for key in MetricDefinition.model_fields if key != "dsl"}, dsl=dsl)
        )
    return tuple(metrics)


def load_semantic_context(user_id: str, snapshot: CatalogSnapshot) -> SemanticContext:
    with get_db_connection() as conn:
        connection = lock_semantic_connection(conn, user_id, snapshot, read=True)
        return SemanticContext(
            semantic_version=connection["semantic_version"],
            labels=visible_labels(conn, snapshot),
            metrics=visible_metrics(conn, snapshot, enabled_only=True),
        )


def check_metric_aliases(
    conn: Connection, connection_id: str, dsl: MetricDSL, *, exclude_id: str | None = None
) -> None:
    aliases = {normalize_alias(value) for value in (dsl.key, dsl.name, *dsl.synonyms)}
    rows = conn.execute(
        sa.select(business_metrics).where(
            business_metrics.c.connection_id == connection_id,
            business_metrics.c.enabled.is_(True),
        )
    ).mappings()
    for row in rows:
        if row["id"] == exclude_id:
            continue
        other = MetricDSL.model_validate_json(row["dsl_json"])
        if aliases & {normalize_alias(value) for value in (other.key, other.name, *other.synonyms)}:
            # Do not disclose the conflicting (possibly hidden) definition.
            raise HTTPException(409, "Metric aliases conflict with an enabled definition")
