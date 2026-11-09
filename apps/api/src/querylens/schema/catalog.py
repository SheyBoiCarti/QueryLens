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
            ca_cert=conn_dict["ca_cert"],
            tls_mode=conn_dict.get("tls_mode", "verify-full"),
        )

        return SchemaInspector.discover_candidate_tables(engine, conn_dict["engine"])

    def discover_columns(self, user_id: str, connection_id: str) -> dict[str, list[str]]:
        connection = verify_connection_ownership(connection_id, user_id)
        password = decrypt_credential(connection["encrypted_password"], connection_id=connection_id)
        engine = get_registry().get_or_create(
            connection_id=connection_id,
            engine_name=connection["engine"],
            host=connection["host"],
            port=connection["port"],
            database=connection["database"],
            username=connection["username"],
            password=password,
            tls_enabled=connection["tls_enabled"],
            ca_cert=connection["ca_cert"],
            tls_mode=connection.get("tls_mode", "verify-full"),
        )
        return SchemaInspector.discover_columns(engine, connection["engine"])

    def get_catalog(self, user_id: str, connection_id: str) -> CatalogSnapshot:
        """Get latest catalog snapshot, refreshing if none exists."""
        connection = verify_connection_ownership(connection_id, user_id)
        snapshot = get_latest_snapshot(connection_id)
        if snapshot is None or snapshot.policy_version != connection["policy_version"]:
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
            ca_cert=conn_dict["ca_cert"],
            tls_mode=conn_dict.get("tls_mode", "verify-full"),
        )

        allowed_tables = json.loads(conn_dict["allowed_tables"]) if conn_dict["allowed_tables"] else {}

        snapshot = SchemaInspector.reflect_visible_catalog(
            connection_id=connection_id,
            engine=engine,
            engine_name=conn_dict["engine"],
            allowed_tables=allowed_tables,
            policy_version=conn_dict["policy_version"],
        )

        from querylens.persistence.session import get_db_connection
        from querylens.persistence.tables import connections
        import sqlalchemy as sa

        with get_db_connection() as conn:
            version = conn.execute(
                sa.select(connections.c.policy_version).where(connections.c.id == connection_id).with_for_update()
            ).scalar_one()
            if version != snapshot.policy_version:
                raise ValueError("Connection policy changed during schema refresh; refresh again")
            save_snapshot(snapshot, conn)
        return snapshot
