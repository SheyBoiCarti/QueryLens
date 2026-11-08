"""Durable context is atomic, bounded metadata, never a persisted answer."""

import datetime as dt
import json
from decimal import Decimal

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from querylens.domain.analytics import (
    AppliedFilter,
    BoundParameter,
    ObjectReference,
    ResolvedParameters,
    RunContext,
)
from querylens.persistence.repositories.query_runs import QueryRunRepository, TERMINAL_STATES
from querylens.persistence.tables import query_runs


def context(snapshot):
    return RunContext(
        effective_question="List customer IDs",
        canonical_sql_template="SELECT id FROM public.customers",
        referenced_objects=(
            ObjectReference(
                namespace="public",
                table_name="customers",
                column_name="id",
                canonical_type="integer",
                db_type="integer",
            ),
        ),
        snapshot_hash=snapshot.snapshot_hash,
        policy_version=1,
        semantic_version=1,
    )


def test_old_create_defaults_and_atomic_completion(analytics_env):
    env = analytics_env
    repo = QueryRunRepository()
    created = repo.create("legacy", env.owner_id, env.connection_id, "List IDs")
    assert created["origin"] == "natural_language"
    old = repo.get("legacy")
    assert old["run_context_json"] is None and old["snapshot_hash"] is None
    ctx = context(env.snapshot)
    assert repo.complete(
        "legacy", ctx, "SELECT id FROM public.customers LIMIT 101", ["Visible only"], ["Bounded"], True
    )
    run = repo.get("legacy")
    assert run["status"] == "completed" and run["state_version"] == old["state_version"] + 1
    assert RunContext.model_validate_json(run["run_context_json"]) == ctx
    assert run["snapshot_hash"] == ctx.snapshot_hash
    assert run["policy_version"] == 1 and run["semantic_version"] == 1
    assert json.loads(run["assumptions"]) == ["Visible only"]
    assert json.loads(run["warnings"]) == ["Bounded"] and run["truncated"]
    assert run["canonical_sql"].endswith("LIMIT 101")
    assert not repo.complete("legacy", ctx, "SELECT 1", [], [], False)
    assert repo.get("legacy") == run


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATES))
def test_completion_cannot_overwrite_terminal_metadata(analytics_env, terminal):
    env = analytics_env
    repo = QueryRunRepository()
    repo.create("race", env.owner_id, env.connection_id, "Question")
    repo.update_state("race", terminal, safe_message="Keep this")
    before = repo.get("race")
    assert not repo.complete("race", context(env.snapshot), "SELECT 1", [], [], False)
    assert repo.get("race") == before
    assert not repo.complete("absent", context(env.snapshot), "SELECT 1", [], [], False)


def test_context_strict_roundtrip_and_limits(analytics_env, monkeypatch):
    ctx = context(analytics_env.snapshot)
    data = ctx.model_dump(mode="json")
    assert RunContext.model_validate_json(json.dumps(data)) == ctx
    for forbidden in ("rows", "row_count", "computed_measures", "summary"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted") as error:
            RunContext.model_validate_json(json.dumps({**data, forbidden: []}))
        assert error.value.errors()[0]["loc"] == (forbidden,)
    with pytest.raises(ValidationError) as error:
        RunContext.model_validate_json(json.dumps({**data, "semantic_version": "1"}))
    assert error.value.errors()[0]["loc"] == ("semantic_version",)
    with pytest.raises(ValidationError):
        ctx.semantic_version = 2
    from querylens.config import get_settings

    monkeypatch.setattr(get_settings(), "max_request_bytes", 100)
    with pytest.raises(ValidationError, match="budget"):
        RunContext.model_validate_json(ctx.model_dump_json())


@pytest.mark.parametrize(
    "scalar_type,value",
    [
        ("date", dt.date(2026, 11, 8)),
        ("datetime", dt.datetime(2026, 11, 8, tzinfo=dt.timezone.utc)),
        ("decimal", Decimal("12345678901234567890.01")),
        ("string", "50% 'λ'"),
        ("integer", 3),
        ("float", 0.5),
        ("boolean", True),
    ],
)
def test_frozen_binding_declarations_roundtrip(scalar_type, value):
    binding = BoundParameter(name="p1", scalar_type=scalar_type, value=value)
    assert BoundParameter.model_validate_json(binding.model_dump_json()) == binding
    assert type(BoundParameter.model_validate_json(binding.model_dump_json()).value) is type(value)
    with pytest.raises(ValidationError):
        binding.value = "changed"
    assert ResolvedParameters().bindings == ()
    assert ResolvedParameters().values == {}


def test_filter_and_resolved_values_cannot_be_mutated():
    values = {"country": "South Africa", "period": {"mode": "this_month"}}
    resolved = ResolvedParameters(values=values)
    values["country"] = "changed"
    values["period"]["mode"] = "changed"
    assert resolved.values["country"] == "South Africa"
    assert resolved.values["period"]["mode"] == "this_month"
    with pytest.raises(TypeError):
        resolved.values["period"]["mode"] = "changed"
    assert ResolvedParameters.model_validate_json(resolved.model_dump_json()) == resolved
    with pytest.raises(ValidationError):
        BoundParameter(name="p", scalar_type="integer", value=True)
    with pytest.raises(ValidationError):
        AppliedFilter(
            slot_id="x",
            column=ObjectReference(
                namespace="public", table_name="t", column_name="c", canonical_type="integer", db_type="int"
            ),
            operator="=",
            value={"rows": [1]},
        )


def test_origin_constraint_and_relationship_metadata(analytics_env):
    env = analytics_env
    repo = QueryRunRepository()
    parent = repo.create("parent", env.owner_id, env.connection_id, "Parent")
    child = repo.create(
        "child",
        env.owner_id,
        env.connection_id,
        "Child",
        origin="manual_sql",
        parent_query_id=parent["query_id"],
        source_query_id=parent["query_id"],
        saved_question_id="removed-definition",
        saved_question_version=3,
        submitted_sql="SELECT id FROM customers",
        saved_definition_json='{"revision":3}',
    )
    assert child["saved_question_version"] == 3
    assert repo.get("child")["submitted_sql"] == "SELECT id FROM customers"
    with env.engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            query_runs.insert().values(
                id="invalid", user_id=env.owner_id, connection_id=env.connection_id, question="bad", origin="arbitrary"
            )
        )


def test_completion_is_one_statement_and_rolls_back_as_a_unit(analytics_env):
    env = analytics_env
    repo = QueryRunRepository()
    repo.create("atomic", env.owner_id, env.connection_id, "List IDs")
    before = repo.get("atomic")
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    with env.engine.connect() as conn:
        transaction = conn.begin()
        sa.event.listen(conn, "before_cursor_execute", capture)
        assert QueryRunRepository(conn).complete(
            "atomic", context(env.snapshot), "SELECT id FROM public.customers", [], [], False
        )
        assert len(statements) == 1 and statements[0].startswith("UPDATE query_runs")
        transaction.rollback()
    assert repo.get("atomic") == before


def test_context_preserves_filter_and_reference_versions(analytics_env):
    from querylens.domain.analytics import LabelReference, MetricReference

    ctx = context(analytics_env.snapshot)
    ctx = RunContext(
        **{
            **ctx.model_dump(),
            "applied_filters": (
                AppliedFilter(
                    slot_id="country",
                    column=ObjectReference(
                        namespace="public",
                        table_name="customers",
                        column_name="country",
                        canonical_type="string",
                        db_type="text",
                    ),
                    operator="=",
                    value="South Africa",
                ),
            ),
            "metric_references": (MetricReference(id="metric", key="customers", version=3, dsl_hash="a" * 64),),
            "label_references": (
                LabelReference(
                    namespace="public",
                    table_name="customers",
                    display_name="Customers",
                    description="Customer registry",
                    version=5,
                ),
            ),
        }
    )
    restored = RunContext.model_validate_json(ctx.model_dump_json())
    assert restored == ctx
    assert restored.metric_references[0].version == 3
    assert restored.label_references[0].version == 5
    assert type(restored.applied_filters[0].value) is str


@pytest.mark.parametrize(
    "scalar_type,value",
    [("decimal", "invalid"), ("decimal", "NaN"), ("date", "2026-99-99"), ("float", float("inf")), ("integer", True)],
)
def test_invalid_typed_bindings_are_validation_errors(scalar_type, value):
    with pytest.raises(ValidationError):
        BoundParameter.model_validate_json(json.dumps({"name": "p", "scalar_type": scalar_type, "value": value}))


@pytest.mark.parametrize(
    "start,end",
    [
        (dt.date(2026, 11, 1), dt.date(2026, 12, 1)),
        (dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc), dt.datetime(2026, 12, 1, tzinfo=dt.timezone.utc)),
    ],
)
def test_resolved_date_boundaries_roundtrip_preserves_types(start, end):
    from querylens.domain.analytics import ResolvedDateRange

    resolved = ResolvedParameters(resolved_dates=(ResolvedDateRange(slot_id="period", start=start, end_exclusive=end),))
    restored = ResolvedParameters.model_validate_json(resolved.model_dump_json())
    assert restored == resolved
    assert type(restored.resolved_dates[0].start) is type(start)
    with pytest.raises(ValidationError):
        ResolvedDateRange(slot_id="period", start=end, end_exclusive=start)
