"""Task 07.02 Tests: Retry policy and repair decision contracts.

Contracts: C07, C08.
Assertions:
1. A permanently repairable error produces at most three provider calls total and a failed/MAX_ATTEMPTS_EXCEEDED result.
2. Each nonrepairable category makes zero repair calls.
3. Exhausted deadline/token/cost budget makes zero further calls.
4. max_rows cannot reset from a user value to a default during repair.
"""

from __future__ import annotations

import time

from querylens.pipeline.errors import ClassifiedError
from querylens.pipeline.repair import RepairPolicy, RunAttemptBudget


def test_permanently_repairable_error_at_most_two_repairs() -> None:
    # 1 initial attempt + at most 2 repairs = 3 attempts total
    policy = RepairPolicy()
    budget = RunAttemptBudget(start_time=time.monotonic(), total_deadline_sec=30.0)

    repairable_err = ClassifiedError(
        category="syntax",
        code="SYNTAX_ERROR",
        safe_message="Syntax error",
        repairable=True,
    )

    # Attempt 1 failed -> Repair 1 (allowed)
    d1 = policy.decide(repairable_err, attempt_number=1, budget=budget)
    assert d1.can_repair is True

    # Attempt 2 failed -> Repair 2 (allowed)
    d2 = policy.decide(repairable_err, attempt_number=2, budget=budget)
    assert d2.can_repair is True

    # Attempt 3 failed -> Cannot repair (MAX_ATTEMPTS_EXCEEDED)
    d3 = policy.decide(repairable_err, attempt_number=3, budget=budget)
    assert d3.can_repair is False
    assert d3.reason == "MAX_ATTEMPTS_EXCEEDED"


def test_nonrepairable_categories_make_zero_repairs() -> None:
    policy = RepairPolicy()
    budget = RunAttemptBudget(start_time=time.monotonic(), total_deadline_sec=30.0)

    non_repairable_categories = [
        ("policy", "POLICY_VIOLATION"),
        ("permission", "PERMISSION_DENIED"),
        ("timeout", "STATEMENT_TIMEOUT"),
        ("connection", "CONNECTION_ERROR"),
        ("ambiguous_intent", "AMBIGUOUS_INTENT"),
        ("unknown", "UNKNOWN_ERROR"),
    ]

    for cat, code in non_repairable_categories:
        err = ClassifiedError(
            category=cat,  # type: ignore[arg-type]
            code=code,
            safe_message="Failed",
            repairable=False,
        )
        decision = policy.decide(err, attempt_number=1, budget=budget)
        assert decision.can_repair is False
        assert decision.reason in ("NON_REPAIRABLE_CATEGORY", "POLICY_VIOLATION", "PERMISSION_DENIED", "TIMEOUT", "AMBIGUOUS_INTENT")


def test_exhausted_deadline_or_token_budget_zero_calls() -> None:
    policy = RepairPolicy()
    repairable_err = ClassifiedError(
        category="syntax",
        code="SYNTAX_ERROR",
        safe_message="Syntax error",
        repairable=True,
    )

    # 1. Exhausted deadline (cleanup reserve is 5s)
    # If run started 26s ago with 30s deadline, remaining is 4s < 5s reserve
    past_budget = RunAttemptBudget(start_time=time.monotonic() - 26.0, total_deadline_sec=30.0, cleanup_reserve_sec=5.0)
    decision = policy.decide(repairable_err, attempt_number=1, budget=past_budget)
    assert decision.can_repair is False
    assert decision.reason == "DEADLINE_EXCEEDED"

    # 2. Exhausted token budget (cumulative >= 16000)
    token_budget = RunAttemptBudget(
        start_time=time.monotonic(),
        total_deadline_sec=30.0,
        cumulative_tokens=16500,
        max_cumulative_tokens=16000,
    )
    decision = policy.decide(repairable_err, attempt_number=1, budget=token_budget)
    assert decision.can_repair is False
    assert decision.reason == "TOKEN_BUDGET_EXCEEDED"


def test_max_rows_retained_during_repair() -> None:
    # Ensure repair context keeps original user max_rows
    from querylens.pipeline.repair_context import assemble_repair_context
    from querylens.pipeline.context import SchemaContext

    schema_ctx = SchemaContext(tables=[], formatted_schema="schema")
    user_max_rows = 42

    ctx = assemble_repair_context(
        question="Show top users",
        dialect="postgres",
        schema_context=schema_ctx,
        prior_sql="SELECT foo FROM bar",
        classified_error=ClassifiedError(
            category="unknown_identifier",
            code="UNDEFINED_COLUMN",
            safe_message="foo does not exist",
            repairable=True,
        ),
        max_rows=user_max_rows,
    )
    assert ctx.max_rows == 42
    assert ctx.max_rows != 100  # Default is not substituted
