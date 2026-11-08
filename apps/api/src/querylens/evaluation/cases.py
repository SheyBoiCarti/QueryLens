"""Benchmark evaluation cases schema, loader, and suite validator (Contracts C06, C10)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

ExpectedBehavior = Literal["answerable", "clarification", "rejected"]
CategoryName = Literal[
    "filters",
    "aggregates",
    "joins",
    "subqueries",
    "temporal",
    "complex_analytical",
    "ambiguity",
    "adversarial",
]


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationCase(StrictBaseModel):
    id: str
    category: CategoryName
    dialect: str = "both"  # "postgresql", "mysql", or "both"
    question: str
    expected_behavior: ExpectedBehavior
    reference_sql: str | None = None
    reference_result_json: str | None = None
    order_keys: list[str] = Field(default_factory=list)
    tie_breakers: list[str] = Field(default_factory=list)


def load_cases(file_path: str | Path, engine: str | None = None) -> list[EvaluationCase]:
    """Load and validate benchmark evaluation cases from JSON file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Benchmark case file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Benchmark case file must contain a JSON array of cases")

    cases: list[EvaluationCase] = []
    seen_ids: set[str] = set()

    for item in data:
        case = EvaluationCase(**item)
        if case.id in seen_ids:
            raise ValueError(f"Duplicate benchmark case ID detected: {case.id}")
        seen_ids.add(case.id)

        if engine:
            norm_engine = "postgres" if engine.lower() in ("postgres", "postgresql") else engine.lower()
            if case.dialect != "both" and case.dialect.lower() != norm_engine:
                continue

        cases.append(case)

    return cases
