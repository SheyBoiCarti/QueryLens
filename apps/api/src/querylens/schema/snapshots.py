"""Snapshot storage, versioning, and atomic swap (Contracts C05, C08)."""

from __future__ import annotations

import datetime
import json
import uuid
import sqlalchemy as sa
from sqlalchemy.engine import Connection

from querylens.domain.schema import CatalogSnapshot
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import schema_snapshots


def save_snapshot(snapshot: CatalogSnapshot, conn: Connection | None = None) -> None:
    """Persist catalog snapshot."""
    catalog_json = json.dumps(snapshot.model_dump(), sort_keys=True)
    snap_id = str(uuid.uuid4())
    stmt = schema_snapshots.insert().values(
        id=snap_id,
        connection_id=snapshot.connection_id,
        snapshot_hash=snapshot.snapshot_hash,
        policy_version=snapshot.policy_version,
        catalog_json=catalog_json,
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    if conn:
        conn.execute(stmt)
    else:
        with get_db_connection() as c:
            c.execute(stmt)


def get_latest_snapshot(connection_id: str, conn: Connection | None = None) -> CatalogSnapshot | None:
    """Fetch the latest catalog snapshot for a connection."""
    stmt = (
        sa.select(schema_snapshots)
        .where(schema_snapshots.c.connection_id == connection_id)
        .order_by(schema_snapshots.c.created_at.desc(), schema_snapshots.c.policy_version.desc())
        .limit(1)
    )
    if conn:
        row = conn.execute(stmt).fetchone()
    else:
        with get_db_connection() as c:
            row = c.execute(stmt).fetchone()

    if row is None:
        return None

    m = dict(row._mapping)
    catalog_data = json.loads(m["catalog_json"])
    return CatalogSnapshot.model_validate(catalog_data)
