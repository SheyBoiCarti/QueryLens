"""Visible label replacement, preserving hidden records inside the transaction."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
import sqlalchemy as sa

from querylens.domain.analytics import LabelReference
from querylens.domain.schema import CatalogSnapshot
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import catalog_labels
from querylens.semantics.versions import (
    advance_semantic_version,
    label_is_visible,
    lock_semantic_connection,
    normalize_alias,
    visible_labels,
)


class CatalogLabelInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    namespace: Annotated[str, Field(min_length=1, max_length=255)]
    table_name: Annotated[str, Field(min_length=1, max_length=255)]
    column_name: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    display_name: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(max_length=2000)] | None = None

    @field_validator("display_name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not normalize_alias(value):
            raise ValueError("Display name must contain non-whitespace characters")
        return value


def replace_labels(
    user_id: str, snapshot: CatalogSnapshot, expected_semantic_version: int, labels: list[CatalogLabelInput]
) -> tuple[int, tuple[LabelReference, ...]]:
    with get_db_connection() as conn:
        connection = lock_semantic_connection(conn, user_id, snapshot)
        if connection["semantic_version"] != expected_semantic_version:
            raise HTTPException(409, "Semantic definitions changed; reload before saving")
        targets = set()
        aliases = set()
        for label in labels:
            if not label_is_visible(label, snapshot):
                raise HTTPException(422, "Label target is not visible in the current catalog")
            target = (label.namespace, label.table_name, label.column_name)
            scope = (
                label.namespace,
                label.table_name if label.column_name is not None else None,
                normalize_alias(label.display_name),
            )
            if target in targets or scope in aliases:
                raise HTTPException(409, "Duplicate label target or display name in its scope")
            targets.add(target)
            aliases.add(scope)
        rows = (
            conn.execute(
                sa.select(catalog_labels).where(
                    catalog_labels.c.connection_id == snapshot.connection_id,
                )
            )
            .mappings()
            .all()
        )
        existing = {(r["namespace"], r["table_name"], r["column_name"]): r for r in rows}
        visible_targets = {(item.namespace, item.table_name, item.column_name) for item in visible_labels(conn, snapshot)}
        for target, hidden in existing.items():
            if target in visible_targets:
                continue
            scope = (
                hidden["namespace"],
                hidden["table_name"] if hidden["column_name"] is not None else None,
                normalize_alias(hidden["display_name"]),
            )
            if scope in aliases:
                raise HTTPException(409, "Display name conflicts with an existing label in its scope")
        for old in visible_labels(conn, snapshot):
            target = (old.namespace, old.table_name, old.column_name)
            if target not in targets:
                conn.execute(catalog_labels.delete().where(catalog_labels.c.id == existing[target]["id"]))
        now = dt.datetime.now(dt.timezone.utc)
        for label in labels:
            previous = existing.get((label.namespace, label.table_name, label.column_name))
            values = label.model_dump()
            if previous is None:
                conn.execute(
                    catalog_labels.insert().values(
                        id=str(uuid.uuid4()),
                        connection_id=snapshot.connection_id,
                        **values,
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif any(previous[key] != value for key, value in values.items()):
                conn.execute(
                    catalog_labels.update()
                    .where(catalog_labels.c.id == previous["id"])
                    .values(**values, version=previous["version"] + 1, updated_at=now)
                )
        advance_semantic_version(conn, snapshot.connection_id)
        return connection["semantic_version"] + 1, visible_labels(conn, snapshot)
