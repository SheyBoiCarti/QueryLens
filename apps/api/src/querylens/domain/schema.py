"""Domain models and canonical representations for database schemas (Contracts C05, C09)."""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


CanonicalType = Literal[
    "integer",
    "decimal",
    "float",
    "string",
    "boolean",
    "date",
    "datetime",
]

Cardinality = Literal[
    "many_to_one",
    "one_to_many",
    "one_to_one",
    "many_to_many",
    "unknown",
]


class ColumnMetadata(StrictBaseModel):
    name: str = Field(..., description="Column identifier name")
    canonical_type: CanonicalType
    db_type: str = Field(..., description="Engine-native data type")
    nullable: bool = True
    primary_key: bool = False
    comment: str | None = None


class ForeignKeyConstraint(StrictBaseModel):
    name: str | None = None
    source_columns: list[str] = Field(..., description="Ordered source column names")
    target_table: str = Field(..., description="Referenced target table")
    target_namespace: str | None = None
    target_columns: list[str] = Field(..., description="Ordered target column names")
    cardinality: Cardinality = "many_to_one"
    confidence: float = 1.0


class IndexMetadata(StrictBaseModel):
    name: str
    columns: list[str]
    unique: bool = False


class TableMetadata(StrictBaseModel):
    name: str = Field(..., description="Table name")
    namespace: str = Field(default="public", description="Schema/Database namespace")
    columns: list[ColumnMetadata] = Field(default_factory=list)
    primary_key_columns: list[str] = Field(default_factory=list)
    foreign_keys: list[ForeignKeyConstraint] = Field(default_factory=list)
    indexes: list[IndexMetadata] = Field(default_factory=list)
    comment: str | None = None


class CatalogSnapshot(StrictBaseModel):
    connection_id: str
    engine: str
    policy_version: int = 1
    tables: list[TableMetadata] = Field(default_factory=list)
    snapshot_hash: str = ""

    def compute_hash(self) -> str:
        """Compute canonical SHA-256 hash across sorted visible objects (Contract C05)."""
        # Sort tables by namespace and name
        sorted_tables = []
        for t in sorted(self.tables, key=lambda x: (x.namespace, x.name)):
            # Sort columns
            cols = [
                {
                    "name": c.name,
                    "canonical_type": c.canonical_type,
                    "db_type": c.db_type,
                    "nullable": c.nullable,
                    "primary_key": c.primary_key,
                }
                for c in sorted(t.columns, key=lambda c: c.name)
            ]
            # Sort foreign keys
            fks = [
                {
                    "source": fk.source_columns,
                    "target_table": fk.target_table,
                    "target_namespace": fk.target_namespace,
                    "target_columns": fk.target_columns,
                    "cardinality": fk.cardinality,
                }
                for fk in sorted(t.foreign_keys, key=lambda f: (f.target_table, f.source_columns))
            ]
            sorted_tables.append(
                {
                    "namespace": t.namespace,
                    "name": t.name,
                    "columns": cols,
                    "primary_key": sorted(t.primary_key_columns),
                    "foreign_keys": fks,
                }
            )

        canonical_dict = {
            "engine": self.engine,
            "policy_version": self.policy_version,
            "tables": sorted_tables,
        }
        canonical_str = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
