"""Schema reflection and filter inspector (Contracts C02, C03, C05)."""

from __future__ import annotations

import re
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
        inspector = sa.inspect(engine)
        discovered: list[str] = []

        schemas = inspector.get_schema_names()
        for s in schemas:
            if is_system_schema(engine_name, s):
                continue
            tables = inspector.get_table_names(schema=s)
            for t in tables:
                discovered.append(f"{s}.{t}")

        return sorted(discovered)

    @staticmethod
    def discover_columns(engine: Engine, engine_name: str) -> dict[str, list[str]]:
        """Discover selectable identifiers, never row values or SQL expressions."""
        inspector = sa.inspect(engine)
        result: dict[str, list[str]] = {}
        for namespace in inspector.get_schema_names():
            if is_system_schema(engine_name, namespace):
                continue
            for table in inspector.get_table_names(schema=namespace):
                result[f"{namespace}.{table}"] = [col["name"] for col in inspector.get_columns(table, schema=namespace)]
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

        inspector = sa.inspect(engine)
        reflected_tables: list[TableMetadata] = []

        for table_name, allowed_cols in allowed_tables.items():
            namespace, separator, name = table_name.partition(".")
            if not separator:
                namespace, name = inspector.default_schema_name or "public", table_name
            if is_system_schema(engine_name, namespace):
                continue
            # Get columns
            try:
                raw_cols = inspector.get_columns(name, schema=namespace)
            except Exception:
                continue

            # Get primary keys
            pk_constraint = inspector.get_pk_constraint(name, schema=namespace)
            pks = set(pk_constraint.get("constrained_columns") or [])

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
            raw_fks = inspector.get_foreign_keys(name, schema=namespace)
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
            raw_indexes = inspector.get_indexes(name, schema=namespace)
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
