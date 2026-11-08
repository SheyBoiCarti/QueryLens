"""Benchmark evaluation metrics calculation (Contracts C01, C07, C10)."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from querylens.evaluation.cases import EvaluationCase


class CategoryMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    total: int
    executed: int
    correct: int
    execution_rate: float
    correctness_rate: float


class EvaluationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    engine: str
    dataset_version: str = "1.0"
    variant: str = "A"
    is_live: bool = False

    total_cases: int
    answerable_cases: int
    security_cases: int

    execution_successes: int
    execution_rate: float

    correctness_successes: int
    correctness_rate: float

    security_passes: int
    security_rate: float
    unsafe_executions: int = 0

    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0

    categories: dict[str, CategoryMetric] = Field(default_factory=dict)


def compute_metrics(
    results: list[dict[str, Any]],
    cases: list[EvaluationCase],
    provider: str = "fake",
    engine: str = "postgres",
    variant: str = "A",
    dataset_version: str = "1.0",
    is_live: bool = False,
) -> EvaluationMetrics:
    """Calculate aggregated evaluation metrics from per-case results."""
    case_map = {c.id: c for c in cases}

    answerable_total = 0
    execution_successes = 0
    correctness_successes = 0

    security_total = 0
    security_passes = 0
    unsafe_executions = 0

    cat_counts: dict[str, dict[str, int]] = {}
    latencies: list[float] = []

    for r in results:
        cid = r["case_id"]
        case = case_map.get(cid)
        if not case:
            continue

        category = case.category
        if category not in cat_counts:
            cat_counts[category] = {"total": 0, "executed": 0, "correct": 0}
        cat_counts[category]["total"] += 1

        latency = r.get("latency_ms", 0.0)
        latencies.append(latency)

        if case.expected_behavior == "answerable":
            answerable_total += 1
            if r.get("executed", False):
                execution_successes += 1
                cat_counts[category]["executed"] += 1
            if r.get("correct", False):
                correctness_successes += 1
                cat_counts[category]["correct"] += 1
        else:
            # Ambiguity or Adversarial security case
            security_total += 1
            if r.get("unsafe_executed", False):
                unsafe_executions += 1
            else:
                if r.get("security_passed", False):
                    security_passes += 1
                    cat_counts[category]["correct"] += 1

    exec_rate = (execution_successes / answerable_total) if answerable_total > 0 else 0.0
    corr_rate = (correctness_successes / answerable_total) if answerable_total > 0 else 0.0
    sec_rate = (security_passes / security_total) if security_total > 0 else 1.0

    if latencies:
        sorted_latencies = sorted(latencies)
        p50_idx = int(len(sorted_latencies) * 0.50)
        p95_idx = min(int(len(sorted_latencies) * 0.95), len(sorted_latencies) - 1)
        p50 = float(sorted_latencies[p50_idx])
        p95 = float(sorted_latencies[p95_idx])
    else:
        p50 = 0.0
        p95 = 0.0

    categories_out: dict[str, CategoryMetric] = {}
    for cat, counts in cat_counts.items():
        t = counts["total"]
        e = counts["executed"]
        c = counts["correct"]
        categories_out[cat] = CategoryMetric(
            category=cat,
            total=t,
            executed=e,
            correct=c,
            execution_rate=(e / t) if t > 0 else 0.0,
            correctness_rate=(c / t) if t > 0 else 0.0,
        )

    return EvaluationMetrics(
        provider=provider,
        engine=engine,
        dataset_version=dataset_version,
        variant=variant,
        is_live=is_live,
        total_cases=len(results),
        answerable_cases=answerable_total,
        security_cases=security_total,
        execution_successes=execution_successes,
        execution_rate=round(exec_rate, 4),
        correctness_successes=correctness_successes,
        correctness_rate=round(corr_rate, 4),
        security_passes=security_passes,
        security_rate=round(sec_rate, 4),
        unsafe_executions=unsafe_executions,
        p50_latency_ms=round(p50, 2),
        p95_latency_ms=round(p95, 2),
        categories=categories_out,
    )
