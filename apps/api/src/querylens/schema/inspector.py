"""Schema reflection and filter inspector (Contracts C02, C03, C05)."""

from __future__ import annotations

import re
from collections import defaultdict
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from querylens.domain.schema import (
    CatalogSnapshot,
    ColumnMetadata,
    ForeignKeyConstraint,
    IndexMetadata,
    TableMetadata,
)
from querylens.schema.normalizer import normalize_data_type, normalize_namespace

# System / Temp schema regexes to exclude strictly (Contract C05)
PG_SYSTEM_SCHEMAS = re.compile(r"^(information_schema|pg_catalog|pg_toast|pg_temp_.*|pg_toast_temp_.*)$", re.IGNORECASE)
MYSQL_SYSTEM_DATABASES = re.compile(r"^(information_schema|mysql|performance_schema|sys)$", re.IGNORECASE)


def is_system_schema(engine_name: str, schema_name: str) -> bool:
    """Check if schema/database is an internal system schema."""
    if not schema_name:
        return False
    if engine_name == "postgresql":
        return bool(PG_SYSTEM_SCHEMAS.match(schema_name))
    elif engine_name == "mysql":
        return bool(MYSQL_SYSTEM_DATABASES.match(schema_name))
    return False


class SchemaInspector:
    """Reflects schema objects strictly matching owner-authorized visibility policies."""

    @staticmethod
    def discover_candidate_tables(engine: Engine, engine_name: str) -> list[str]:
        """Discover candidate table names in approved namespaces without sampling rows."""
        with engine.connect() as connection:
            inspector = sa.inspect(connection)
            discovered: list[str] = []

            schemas = [inspector.default_schema_name] if engine_name == "mysql" else inspector.get_schema_names()
            for s in schemas:
                if not s or is_system_schema(engine_name, s):
                    continue
                tables = inspector.get_table_names(schema=s)
                for t in tables:
                    discovered.append(f"{s}.{t}")

            return sorted(discovered)

    @staticmethod
    def discover_columns(engine: Engine, engine_name: str) -> dict[str, list[str]]:
        """Discover selectable identifiers, never row values or SQL expressions."""
        with engine.connect() as connection:
            inspector = sa.inspect(connection)
            result: dict[str, list[str]] = {}
            namespaces = [inspector.default_schema_name] if engine_name == "mysql" else inspector.get_schema_names()
            for namespace in namespaces:
                if not namespace or is_system_schema(engine_name, namespace):
                    continue
                for (_, table), columns in inspector.get_multi_columns(schema=namespace).items():
                    result[f"{namespace}.{table}"] = [column["name"] for column in columns]
            return result

    @staticmethod
    def reflect_visible_catalog(
        connection_id: str,
        engine: Engine,
        engine_name: str,
        allowed_tables: dict[str, list[str]],
        policy_version: int = 1,
    ) -> CatalogSnapshot:
        """Reflect metadata only for explicitly allowed tables and columns."""
        # Contract C05: Empty/omitted selections allow no analytics objects
        if not allowed_tables:
            snap = CatalogSnapshot(
                connection_id=connection_id,
                engine=engine_name,
                policy_version=policy_version,
                tables=[],
            )
            snap.snapshot_hash = snap.compute_hash()
            return snap

        with engine.connect() as connection:
            inspector = sa.inspect(connection)
            reflected_tables: list[TableMetadata] = []
            # Fetch each metadata kind once per namespace. Per-table reflection
            # multiplies network round trips on hosted databases.
            names_by_namespace: dict[str, list[str]] = defaultdict(list)
            for table_name in allowed_tables:
                namespace, separator, name = table_name.partition(".")
                if not separator:
                    namespace, name = inspector.default_schema_name or "public", table_name
                if namespace and not is_system_schema(engine_name, namespace):
                    names_by_namespace[namespace].append(name)
            raw_columns = {}
            primary_keys = {}
            foreign_keys = {}
            table_indexes = {}
            for namespace, names in names_by_namespace.items():
                raw_columns.update(inspector.get_multi_columns(schema=namespace, filter_names=names))
                primary_keys.update(inspector.get_multi_pk_constraint(schema=namespace, filter_names=names))
                foreign_keys.update(inspector.get_multi_foreign_keys(schema=namespace, filter_names=names))
                table_indexes.update(inspector.get_multi_indexes(schema=namespace, filter_names=names))

            for table_name, allowed_cols in allowed_tables.items():
                namespace, separator, name = table_name.partition(".")
                if not separator:
                    namespace, name = inspector.default_schema_name or "public", table_name
                if not namespace or is_system_schema(engine_name, namespace):
                    continue
                # Get columns
                key = (namespace, name)
                raw_cols = raw_columns.get(key)
                if raw_cols is None:
                    continue

                # Get primary keys
                pk_constraint = primary_keys.get(key)
                pks = set(pk_constraint.get("constrained_columns") or []) if pk_constraint else set()

                # Filter columns
                allowed_cols_set = set(allowed_cols) if allowed_cols else set()
                cols: list[ColumnMetadata] = []
                for c in raw_cols:
                    c_name = c["name"]
                    if allowed_cols_set and c_name not in allowed_cols_set:
                        continue
                    db_type_str = str(c["type"])
                    canonical_t = normalize_data_type(db_type_str)
                    cols.append(
                        ColumnMetadata(
                            name=c_name,
                            canonical_type=canonical_t,
                            db_type=db_type_str,
                            nullable=c.get("nullable", True),
                            primary_key=c_name in pks,
                            comment=c.get("comment"),
                        )
                    )

                # Get foreign keys (only where target table is in allowed_tables)
                fks: list[ForeignKeyConstraint] = []
                raw_fks = foreign_keys.get(key, [])
                for fk in raw_fks:
                    target_table = fk.get("referred_table")
                    target_namespace = fk.get("referred_schema") or namespace
                    target_key = f"{target_namespace}.{target_table}"
                    if target_key not in allowed_tables and target_namespace == inspector.default_schema_name:
                        target_key = target_table
                    if not target_table or target_key not in allowed_tables:
                        continue
                    src_cols = fk.get("constrained_columns", [])
                    tgt_cols = fk.get("referred_columns", [])
                    # Ensure all source cols are allowed
                    if allowed_cols_set and not all(sc in allowed_cols_set for sc in src_cols):
                        continue
                    target_allowed = allowed_tables[target_key]
                    if target_allowed and not all(tc in target_allowed for tc in tgt_cols):
                        continue
                    fks.append(
                        ForeignKeyConstraint(
                            name=fk.get("name"),
                            source_columns=src_cols,
                            target_table=target_table,
                            target_namespace=target_namespace,
                            target_columns=tgt_cols,
                            cardinality="many_to_one",
                        )
                    )

                # Get indexes
                indexes: list[IndexMetadata] = []
                raw_indexes = table_indexes.get(key, [])
                for idx in raw_indexes:
                    idx_cols = [col for col in idx.get("column_names", []) if col is not None]
                    if idx_cols and (not allowed_cols_set or all(ic in allowed_cols_set for ic in idx_cols)):
                        indexes.append(
                            IndexMetadata(
                                name=idx["name"] or f"idx_{table_name}",
                                columns=idx_cols,
                                unique=idx.get("unique", False),
                            )
                        )

                ns = normalize_namespace(engine_name, namespace)
                reflected_tables.append(
                    TableMetadata(
                        name=name,
                        namespace=ns,
                        columns=cols,
                        primary_key_columns=[key for key in pks if any(col.name == key for col in cols)],
                        foreign_keys=fks,
                        indexes=indexes,
                    )
                )

            snapshot = CatalogSnapshot(
                connection_id=connection_id,
                engine=engine_name,
                policy_version=policy_version,
                tables=reflected_tables,
            )
            snapshot.snapshot_hash = snapshot.compute_hash()
            return snapshot
