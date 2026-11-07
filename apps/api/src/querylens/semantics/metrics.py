"""Structured Business Metric DSL and validation (Contracts C05, C10)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
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
    table: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    measure_column: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$")
    aggregation: MetricAggregation
    filters: list[MetricFilter] = Field(default_factory=list)
    grain: list[str] = Field(default_factory=list)
    units: str | None = Field(default=None, max_length=50)

    def compute_hash(self) -> str:
        """Deterministic canonical hash of metric specification."""
        dumped = self.model_dump()
        canonical_str = json.dumps(dumped, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def validate_against_snapshot(self, snapshot: CatalogSnapshot) -> None:
        """Validate that all referenced tables, measures, grains, and filters exist in visible catalog."""
        visible = {t.name.lower(): {c.name.lower() for c in t.columns} for t in snapshot.tables}

        t_lower = self.table.lower()
        if t_lower not in visible:
            raise ValueError(f"Metric table '{self.table}' is not in visible catalog")

        table_cols = visible[t_lower]
        if self.measure_column.lower() not in table_cols and self.measure_column != "*":
            raise ValueError(f"Measure column '{self.measure_column}' not found on table '{self.table}'")

        for f in self.filters:
            col_name = f.column.split(".")[-1].lower()
            if col_name not in table_cols:
                raise ValueError(f"Filter column '{f.column}' not found on table '{self.table}'")

        for g in self.grain:
            g_col = g.split(".")[-1].lower()
            if g_col not in table_cols:
                raise ValueError(f"Grain column '{g}' not found on table '{self.table}'")
