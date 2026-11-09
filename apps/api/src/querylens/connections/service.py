"""Connection domain service implementing CRUD, encryption, and testing (Contracts C02, C03, C04)."""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any
import sqlalchemy as sa
from sqlalchemy.engine import Connection

from querylens.api.errors import AppError, NotFoundError
from querylens.connections.adapters import dispatch_test_connection
from querylens.connections.crypto import decrypt_credential, encrypt_credential
from querylens.connections.models import (
    ConnectionCreate,
    ConnectionResponse,
    ConnectionTestResponse,
    ConnectionUpdate,
)
from querylens.connections.registry import get_registry
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import connections, schema_snapshots


class ConnectionService:
    """Manages database connection entities and secure credentials."""

    def __init__(self, conn: Connection | None = None) -> None:
        self._conn = conn

    def create(self, user_id: str, data: ConnectionCreate) -> ConnectionResponse:
        """Create a new database connection with encrypted credentials."""
        conn_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc)

        from querylens.config import get_settings

        if get_settings().environment == "production" and not data.tls_enabled:
            raise ValueError("Production source connections require TLS")

        # Encrypt password with AES-256-GCM bound to connection ID
        encrypted_pw = encrypt_credential(
            data.password.get_secret_value(),
            connection_id=conn_id,
        )

        allowed_tables = data.allowed_tables
        snapshot = None
        if data.import_schema:
            from querylens.schema.inspector import SchemaInspector

            source_args: dict[str, Any] = dict(
                engine_name=data.engine, host=data.host, port=data.port,
                database=data.database, username=data.username,
                password=data.password.get_secret_value(), tls_enabled=data.tls_enabled,
                ca_cert=data.ca_cert, tls_mode=data.tls_mode,
            )
            success, _, message = dispatch_test_connection(**source_args)
            if not success:
                raise AppError("CONNECTION_FAILED", message)
            try:
                engine = get_registry().get_or_create(connection_id=conn_id, **source_args)
                # An explicit policy, including {}, always takes precedence.
                if "allowed_tables" not in data.model_fields_set:
                    allowed_tables = SchemaInspector.discover_columns(engine, data.engine)
                snapshot = SchemaInspector.reflect_visible_catalog(
                    conn_id, engine, data.engine, allowed_tables,
                )
            except Exception as exc:
                raise AppError(
                    "SCHEMA_DISCOVERY_FAILED",
                    "Connected, but could not import the schema. Check that this database user can read table metadata and try again.",
                    422,
                ) from exc
            finally:
                get_registry().dispose(conn_id)

        allowed_tables_json = json.dumps(allowed_tables)

        stmt = connections.insert().values(
            id=conn_id,
            user_id=user_id,
            name=data.name,
            engine=data.engine,
            host=data.host,
            port=data.port,
            database=data.database,
            username=data.username,
            encrypted_password=encrypted_pw,
            tls_enabled=data.tls_enabled,
            tls_mode=data.tls_mode,
            ca_cert=data.ca_cert,
            allowed_tables=allowed_tables_json,
            created_at=now,
            updated_at=now,
        )

        from querylens.schema.snapshots import save_snapshot

        if self._conn:
            self._conn.execute(stmt)
            if snapshot is not None:
                save_snapshot(snapshot, self._conn)
        else:
            with get_db_connection() as c:
                c.execute(stmt)
                if snapshot is not None:
                    save_snapshot(snapshot, c)

        return ConnectionResponse(
            id=conn_id,
            user_id=user_id,
            name=data.name,
            engine=data.engine,
            host=data.host,
            port=data.port,
            database=data.database,
            username=data.username,
            tls_enabled=data.tls_enabled,
            tls_mode=data.tls_mode,
            allowed_tables=allowed_tables,
            created_at=now,
            updated_at=now,
        )

    def list_all(self, user_id: str) -> list[ConnectionResponse]:
        """List all connections owned by user."""
        stmt = sa.select(connections).where(connections.c.user_id == user_id).order_by(connections.c.created_at.desc())
        if self._conn:
            rows = self._conn.execute(stmt).fetchall()
        else:
            with get_db_connection() as c:
                rows = c.execute(stmt).fetchall()

        results = []
        for r in rows:
            m = dict(r._mapping)
            allowed = json.loads(m["allowed_tables"]) if m["allowed_tables"] else {}
            if isinstance(allowed, list):
                allowed = {}
            results.append(
                ConnectionResponse(
                    id=m["id"],
                    user_id=m["user_id"],
                    name=m["name"],
                    engine=m["engine"],
                    host=m["host"],
                    port=m["port"],
                    database=m["database"],
                    username=m["username"],
                    tls_enabled=m["tls_enabled"],
                    tls_mode=m["tls_mode"],
                    allowed_tables=allowed,
                    created_at=m["created_at"],
                    updated_at=m["updated_at"],
                )
            )
        return results

    def get(self, user_id: str, connection_id: str) -> ConnectionResponse:
        """Get connection by ID, verifying ownership (Contract C02: 404 for non-owned)."""
        stmt = sa.select(connections).where(
            connections.c.id == connection_id,
            connections.c.user_id == user_id,
        )
        if self._conn:
            row = self._conn.execute(stmt).fetchone()
        else:
            with get_db_connection() as c:
                row = c.execute(stmt).fetchone()

        if row is None:
            raise NotFoundError("Connection not found")

        m = dict(row._mapping)
        allowed = json.loads(m["allowed_tables"]) if m["allowed_tables"] else {}
        return ConnectionResponse(
            id=m["id"],
            user_id=m["user_id"],
            name=m["name"],
            engine=m["engine"],
            host=m["host"],
            port=m["port"],
            database=m["database"],
            username=m["username"],
            tls_enabled=m["tls_enabled"],
            tls_mode=m["tls_mode"],
            allowed_tables=allowed,
            created_at=m["created_at"],
            updated_at=m["updated_at"],
        )

    def update(
        self,
        user_id: str,
        connection_id: str,
        data: ConnectionUpdate,
    ) -> ConnectionResponse:
        """Update connection settings, preserving omitted password and invalidating pool."""
        # 1. Verify ownership
        self.get(user_id, connection_id)

        from querylens.config import get_settings

        if get_settings().environment == "production" and data.tls_enabled is False:
            raise ValueError("Production source connections require TLS")
        now = datetime.datetime.now(datetime.timezone.utc)
        updates: dict[str, Any] = {"updated_at": now}

        if data.name is not None:
            updates["name"] = data.name
        if data.host is not None:
            updates["host"] = data.host
        if data.port is not None:
            updates["port"] = data.port
        if data.database is not None:
            updates["database"] = data.database
        if data.username is not None:
            updates["username"] = data.username
        if data.tls_enabled is not None:
            updates["tls_enabled"] = data.tls_enabled
        if data.tls_mode is not None:
            updates["tls_mode"] = data.tls_mode
        if data.ca_cert is not None:
            updates["ca_cert"] = data.ca_cert
        if data.allowed_tables is not None:
            updates["allowed_tables"] = json.dumps(data.allowed_tables)

        policy_changed = any(key != "name" for key in data.model_fields_set)
        if policy_changed:
            updates["policy_version"] = connections.c.policy_version + 1

        # Omitted password on PATCH preserves it; new password is re-encrypted
        if data.password is not None:
            encrypted_pw = encrypt_credential(
                data.password.get_secret_value(),
                connection_id=connection_id,
            )
            updates["encrypted_password"] = encrypted_pw

        # Invalidate existing pool in registry on settings change
        get_registry().dispose(connection_id)

        stmt = (
            connections.update()
            .where(connections.c.id == connection_id, connections.c.user_id == user_id)
            .values(**updates)
        )

        if self._conn:
            self._conn.execute(stmt)
            if policy_changed:
                self._conn.execute(schema_snapshots.delete().where(schema_snapshots.c.connection_id == connection_id))
        else:
            with get_db_connection() as c:
                c.execute(stmt)
                if policy_changed:
                    c.execute(schema_snapshots.delete().where(schema_snapshots.c.connection_id == connection_id))
        if policy_changed:
            from querylens.jobs.results import get_result_cache

            get_result_cache().evict_connection(connection_id)
        return self.get(user_id, connection_id)

    def delete(self, user_id: str, connection_id: str) -> None:
        """Delete connection, disposing pool."""
        # Verify ownership
        self.get(user_id, connection_id)
        from querylens.jobs.results import get_result_cache

        get_result_cache().evict_connection(connection_id)

        # Dispose pool
        get_registry().dispose(connection_id)

        stmt = connections.delete().where(
            connections.c.id == connection_id,
            connections.c.user_id == user_id,
        )
        if self._conn:
            self._conn.execute(stmt)
        else:
            with get_db_connection() as c:
                c.execute(stmt)

    def test(self, user_id: str, connection_id: str) -> ConnectionTestResponse:
        """Test connection using target adapter."""
        stmt = sa.select(connections).where(
            connections.c.id == connection_id,
            connections.c.user_id == user_id,
        )
        if self._conn:
            row = self._conn.execute(stmt).fetchone()
        else:
            with get_db_connection() as c:
                row = c.execute(stmt).fetchone()

        if row is None:
            raise NotFoundError("Connection not found")

        m = dict(row._mapping)

        # Decrypt password
        plaintext_pw = decrypt_credential(m["encrypted_password"], connection_id=connection_id)

        success, version, message = dispatch_test_connection(
            engine_name=m["engine"],
            host=m["host"],
            port=m["port"],
            database=m["database"],
            username=m["username"],
            password=plaintext_pw,
            tls_enabled=m["tls_enabled"],
            tls_mode=m["tls_mode"],
            ca_cert=m["ca_cert"],
        )

        return ConnectionTestResponse(
            success=success,
            server_version=version if success else None,
            engine=m["engine"],
            message=message,
        )
