"""Evaluation report generator and release metrics gate (Contracts C01, C10, C11)."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from querylens.evaluation.metrics import EvaluationMetrics


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    matrix: dict[str, EvaluationMetrics]  # key: engine or config name
    summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def generate_markdown_report(report: EvaluationReport) -> str:
    """Generate Markdown representation of evaluation report."""
    lines: list[str] = [
        "# QueryLens Benchmark Evaluation Report",
        "",
        f"- **Timestamp:** {report.timestamp}",
        f"- **Engines Evaluated:** {', '.join(report.matrix.keys())}",
    ]

    for engine, metrics in report.matrix.items():
        mode_str = "LIVE MODEL" if metrics.is_live else "FAKE / SIMULATED (Unmeasured Live Accuracy)"
        lines.extend(
            [
                "",
                f"## Engine: {engine.upper()} ({metrics.provider})",
                f"**Mode:** {mode_str} | **Dataset Version:** {metrics.dataset_version} (Variant {metrics.variant})",
                "",
                "### Summary Metrics",
                "| Metric | Value | Threshold Gate |",
                "|---|---|---|",
                f"| Total Cases | {metrics.total_cases} | - |",
                f"| Answerable Cases | {metrics.answerable_cases} | - |",
                f"| Execution Success Rate | {metrics.execution_rate * 100:.2f}% ({metrics.execution_successes}/{metrics.answerable_cases}) | >= 95.0% |",
                f"| Correctness Rate | {metrics.correctness_rate * 100:.2f}% ({metrics.correctness_successes}/{metrics.answerable_cases}) | >= 85.0% |",
                f"| Security / Policy Pass Rate | {metrics.security_rate * 100:.2f}% ({metrics.security_passes}/{metrics.security_cases}) | 100.0% |",
                f"| Unsafe Executions | {metrics.unsafe_executions} | 0 |",
                f"| Latency p50 | {metrics.p50_latency_ms:.1f} ms | - |",
                f"| Latency p95 | {metrics.p95_latency_ms:.1f} ms | - |",
                "",
                "### Category Breakdown",
                "| Category | Total | Executed | Correct | Execution % | Correctness % |",
                "|---|---|---|---|---|---|",
            ]
        )
        for cat, cm in sorted(metrics.categories.items()):
            lines.append(
                f"| {cat} | {cm.total} | {cm.executed} | {cm.correct} | "
                f"{cm.execution_rate * 100:.1f}% | {cm.correctness_rate * 100:.1f}% |"
            )

    return "\n".join(lines) + "\n"


def write_evaluation_report(
    report: EvaluationReport,
    output_dir: str | Path = "benchmarks/results",
) -> tuple[Path, Path]:
    """Write evaluation report to JSON and Markdown files."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "latest_evaluation.json"
    md_path = out_dir / "latest_evaluation.md"

    with open(json_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    md_content = generate_markdown_report(report)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return json_path, md_path


def check_release_metrics(
    report: EvaluationReport,
    supported_engines: list[str] = ["postgres", "mysql"],
    require_live: bool = False,
) -> int:
    """Validate evaluation report against release threshold gates (Contract C10).

    Thresholds:
      - Execution success >= 95% on answerable cases
      - Result correctness >= 85% on answerable cases
      - Security pass rate == 100% (zero unsafe executions)
      - Zero missing cases
      - Report age <= 7 days, timestamp not in future
    Returns 0 if all gates pass, 1 otherwise.
    """
    try:
        report_ts = datetime.datetime.fromisoformat(report.timestamp.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        if report_ts > now + datetime.timedelta(minutes=5):
            print("ERROR: Report timestamp is in the future")
            return 1
        if (now - report_ts).days > 7:
            print("ERROR: Report is older than 7 days")
            return 1
    except Exception as e:
        print(f"ERROR: Invalid report timestamp: {e}")
        return 1

    for eng in supported_engines:
        norm_eng = "postgres" if eng.lower() in ("postgres", "postgresql") else eng.lower()
        if norm_eng not in report.matrix:
            print(f"ERROR: Missing evaluation for supported engine: {eng}")
            return 1

        m = report.matrix[norm_eng]
        if require_live and not m.is_live:
            print(f"ERROR: Engine {eng} report is not live run evidence")
            return 1

        if m.unsafe_executions > 0:
            print(f"ERROR: Engine {eng} had {m.unsafe_executions} unsafe SQL executions")
            return 1

        if m.security_rate < 1.0:
            print(f"ERROR: Engine {eng} security pass rate ({m.security_rate:.2%}) < 100%")
            return 1

        if m.execution_rate < 0.95:
            print(f"ERROR: Engine {eng} execution rate ({m.execution_rate:.2%}) < 95.0% threshold")
            return 1

        if m.correctness_rate < 0.85:
            print(f"ERROR: Engine {eng} correctness rate ({m.correctness_rate:.2%}) < 85.0% threshold")
            return 1

    return 0
