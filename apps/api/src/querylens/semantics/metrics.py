"""Structured Business Metric DSL and validation (Contracts C05, C10)."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

from querylens.domain.schema import CatalogSnapshot


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


MetricAggregation = Literal[
    "sum",
    "count",
    "count_distinct",
    "avg",
    "min",
    "max",
]

FilterOperator = Literal[
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "is_null",
    "is_not_null",
]


class MetricFilter(StrictBaseModel):
    column: str = Field(..., pattern=r"^[a-zA-Z0-9_.]+$")
    operator: FilterOperator
    value: Any = None


class MetricDSL(StrictBaseModel):
    """Structured declarative DSL for business metrics (Contract C10).

    Excludes raw SQL strings to prevent arbitrary expression injection.
    """

    key: str = Field(..., pattern=r"^[a-z0-9_]+$", max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    table: str = Field(..., pattern=r"^[a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?$")
    measure_column: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    aggregation: MetricAggregation
    filters: list[MetricFilter] = Field(default_factory=list)
    grain: list[str] = Field(default_factory=list)
    units: str | None = Field(default=None, max_length=50)

    synonyms: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=20)

    @field_validator("name", "synonyms")
    @classmethod
    def nonempty_aliases(cls, value):
        aliases = value if isinstance(value, list) else [value]
        if any(not alias.strip() for alias in aliases):
            raise ValueError("Aliases must contain non-whitespace characters")
        return value

    def compute_hash(self) -> str:
        """Deterministic canonical hash of metric specification."""
        dumped = self.model_dump()
        canonical_str = json.dumps(dumped, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def validate_against_snapshot(self, snapshot: CatalogSnapshot) -> None:
        """Validate that all referenced tables, measures, grains, and filters exist in visible catalog."""
        parts = self.table.split(".", 1)
        candidates = [
            table
            for table in snapshot.tables
            if table.name == parts[-1] and (len(parts) == 1 or table.namespace == parts[0])
        ]
        if len(candidates) != 1:
            raise ValueError(f"Metric table '{self.table}' is not uniquely visible in the catalog")
        table = candidates[0]
        table_cols = {column.name for column in table.columns}
        if self.measure_column not in table_cols and self.measure_column != "*":
            raise ValueError(f"Measure column '{self.measure_column}' not found on table '{self.table}'")

        def validate_column(reference: str) -> None:
            parts = reference.split(".")
            allowed = ([parts[-1]], [table.name, parts[-1]], [table.namespace, table.name, parts[-1]])
            if parts not in allowed or parts[-1] not in table_cols:
                raise ValueError(f"Column '{reference}' not found on table '{self.table}'")

        for predicate in self.filters:
            validate_column(predicate.column)
        for column in self.grain:
            validate_column(column)


class MetricDefinition(StrictBaseModel):
    id: str
    connection_id: str
    key: str
    name: str
    description: str | None
    dsl: MetricDSL
    version: int
    enabled: bool
