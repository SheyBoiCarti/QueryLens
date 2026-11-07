"""Catalog service coordinating reflection, candidate table discovery, and refresh (Contract C05)."""

from __future__ import annotations

import json
from querylens.auth.ownership import verify_connection_ownership
from querylens.connections.crypto import decrypt_credential
from querylens.connections.registry import get_registry
from querylens.domain.schema import CatalogSnapshot
from querylens.schema.inspector import SchemaInspector
from querylens.schema.snapshots import get_latest_snapshot, save_snapshot


class CatalogService:
    """Coordinates schema discovery, authorized reflection, and snapshot management."""

    def discover_tables(self, user_id: str, connection_id: str) -> list[str]:
        """Discover candidate table names in authorized target database."""
        conn_dict = verify_connection_ownership(connection_id, user_id)
        pwd = decrypt_credential(conn_dict["encrypted_password"], connection_id=connection_id)

        engine = get_registry().get_or_create(
            connection_id=connection_id,
            engine_name=conn_dict["engine"],
            host=conn_dict["host"],
            port=conn_dict["port"],
            database=conn_dict["database"],
            username=conn_dict["username"],
            password=pwd,
            tls_enabled=conn_dict["tls_enabled"],
        )

        return SchemaInspector.discover_candidate_tables(engine, conn_dict["engine"])

    def get_catalog(self, user_id: str, connection_id: str) -> CatalogSnapshot:
        """Get latest catalog snapshot, refreshing if none exists."""
        verify_connection_ownership(connection_id, user_id)
        snapshot = get_latest_snapshot(connection_id)
        if snapshot is None:
            return self.refresh_catalog(user_id, connection_id)
        return snapshot

    def refresh_catalog(self, user_id: str, connection_id: str) -> CatalogSnapshot:
        """Reflect visible catalog and save new snapshot atomically."""
        conn_dict = verify_connection_ownership(connection_id, user_id)
        pwd = decrypt_credential(conn_dict["encrypted_password"], connection_id=connection_id)

        engine = get_registry().get_or_create(
            connection_id=connection_id,
            engine_name=conn_dict["engine"],
            host=conn_dict["host"],
            port=conn_dict["port"],
            database=conn_dict["database"],
            username=conn_dict["username"],
            password=pwd,
            tls_enabled=conn_dict["tls_enabled"],
        )

        allowed_tables = json.loads(conn_dict["allowed_tables"]) if conn_dict["allowed_tables"] else {}

        # Prior snapshot policy version
        prior = get_latest_snapshot(connection_id)
        new_policy_version = (prior.policy_version + 1) if prior else 1

        snapshot = SchemaInspector.reflect_visible_catalog(
            connection_id=connection_id,
            engine=engine,
            engine_name=conn_dict["engine"],
            allowed_tables=allowed_tables,
            policy_version=new_policy_version,
        )

        save_snapshot(snapshot)
        return snapshot
