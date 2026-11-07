"""Tests for benchmark case suite, evaluation runner, metrics, and report gates (Contracts C01, C06, C10)."""

import datetime
from pathlib import Path
import pytest

from querylens.evaluation.ablations import run_ablations
from querylens.evaluation.cases import EvaluationCase, load_cases
from querylens.evaluation.comparison import compare_result_sets
from querylens.evaluation.metrics import CategoryMetric, EvaluationMetrics
from querylens.evaluation.report import (
    EvaluationReport,
    check_release_metrics,
    generate_markdown_report,
)
from querylens.evaluation.runner import evaluate


def test_benchmark_cases_loading_and_uniqueness():
    repo_root = Path(__file__).resolve().parents[4]
    heldout_path = repo_root / "benchmarks/cases/heldout.json"
    security_path = repo_root / "benchmarks/cases/security.json"

    assert heldout_path.exists(), f"Heldout cases file missing at {heldout_path}"
    assert security_path.exists(), f"Security cases file missing at {security_path}"

    heldout_cases = load_cases(heldout_path)
    security_cases = load_cases(security_path)

    assert len(heldout_cases) == 135
    assert len(security_cases) == 15
    total = len(heldout_cases) + len(security_cases)
    assert total == 150

    # Ensure all IDs are strictly unique
    all_ids = [c.id for c in heldout_cases + security_cases]
    assert len(all_ids) == len(set(all_ids))

    # Validate categories
    categories = {c.category for c in heldout_cases + security_cases}
    expected_categories = {
        "filters",
        "aggregates",
        "joins",
        "subqueries",
        "temporal",
        "complex_analytical",
        "ambiguity",
        "adversarial",
    }
    assert categories == expected_categories


def test_evaluation_runner_offline_mechanics(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[4]
    heldout_path = repo_root / "benchmarks/cases/heldout.json"

    report, exit_code = evaluate(
        engine="postgres",
        provider="fake",
        case_set=heldout_path,
        output_dir=tmp_path,
        variant="A",
    )

    assert exit_code == 0
    assert "postgres" in report.matrix
    metrics = report.matrix["postgres"]
    assert metrics.total_cases == 135
    assert metrics.execution_rate >= 0.95
    assert metrics.security_rate == 1.0

    # Check generated files
    json_report = tmp_path / "latest_evaluation.json"
    md_report = tmp_path / "latest_evaluation.md"
    assert json_report.exists()
    assert md_report.exists()
    assert "QueryLens Benchmark Evaluation Report" in md_report.read_text(encoding="utf-8")


def test_release_metric_threshold_checks():
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    dummy_cat = {
        "filters": CategoryMetric(
            category="filters",
            total=10,
            executed=10,
            correct=10,
            execution_rate=1.0,
            correctness_rate=1.0,
        )
    }

    # 1. Passing metrics
    good_metrics = EvaluationMetrics(
        provider="fake",
        engine="postgres",
        total_cases=100,
        answerable_cases=90,
        security_cases=10,
        execution_successes=90,
        execution_rate=1.0,
        correctness_successes=85,
        correctness_rate=0.94,
        security_passes=10,
        security_rate=1.0,
        unsafe_executions=0,
        categories=dummy_cat,
    )
    good_report = EvaluationReport(
        timestamp=now_iso,
        matrix={"postgres": good_metrics},
    )
    assert check_release_metrics(good_report, supported_engines=["postgres"]) == 0

    # 2. Failing: Low execution rate (< 95%)
    bad_exec = good_metrics.model_copy(update={"execution_rate": 0.92})
    bad_exec_report = EvaluationReport(timestamp=now_iso, matrix={"postgres": bad_exec})
    assert check_release_metrics(bad_exec_report, supported_engines=["postgres"]) == 1

    # 3. Failing: Low correctness rate (< 85%)
    bad_corr = good_metrics.model_copy(update={"correctness_rate": 0.80})
    bad_corr_report = EvaluationReport(timestamp=now_iso, matrix={"postgres": bad_corr})
    assert check_release_metrics(bad_corr_report, supported_engines=["postgres"]) == 1

    # 4. Failing: Unsafe execution detected (> 0)
    unsafe_m = good_metrics.model_copy(update={"unsafe_executions": 1})
    unsafe_report = EvaluationReport(timestamp=now_iso, matrix={"postgres": unsafe_m})
    assert check_release_metrics(unsafe_report, supported_engines=["postgres"]) == 1

    # 5. Failing: Stale report (> 7 days)
    old_ts = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=8)).isoformat()
    old_report = EvaluationReport(timestamp=old_ts, matrix={"postgres": good_metrics})
    assert check_release_metrics(old_report, supported_engines=["postgres"]) == 1


def test_ablations_runner():
    cases = [
        EvaluationCase(
            id="c1",
            category="complex_analytical",
            question="complex query",
            expected_behavior="answerable",
            reference_sql="SELECT id FROM orders;",
        ),
        EvaluationCase(
            id="c2",
            category="joins",
            question="join query",
            expected_behavior="answerable",
            reference_sql="SELECT orders.id FROM orders JOIN customers ON orders.customer_id = customers.id;",
        ),
    ]

    ablation_results = run_ablations(heldout_cases=cases, engine="postgres", provider="fake")
    assert "full_pipeline" in ablation_results
    assert "no_repair" in ablation_results
    assert "no_few_shot" in ablation_results
    assert "no_ranking_no_fewshot" in ablation_results
