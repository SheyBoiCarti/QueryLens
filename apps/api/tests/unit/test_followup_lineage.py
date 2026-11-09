"""Unit tests for follow-up conversation lineage, ancestry validation, and drift detection (Contract C08)."""

import json
import pytest

from querylens.domain.analytics import ObjectReference, RunContext
from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
from querylens.pipeline.followup import (
    FollowUpContext,
    FollowUpContextOversized,
    FollowUpContextStale,
    FollowUpInvalidParentError,
    FollowUpParentNotFoundError,
    resolve_followup_context,
)
from querylens.semantics.versions import SemanticContext


@pytest.fixture
def catalog_snapshot():
    t_orders = TableMetadata(
        name="orders",
        namespace="public",
        columns=[
            ColumnMetadata(name="id", canonical_type="integer", db_type="int", primary_key=True),
            ColumnMetadata(name="country", canonical_type="string", db_type="varchar(50)"),
        ],
        primary_key_columns=["id"],
    )
    snap = CatalogSnapshot(connection_id="conn_1", engine="postgresql", tables=[t_orders])
    snap.snapshot_hash = snap.compute_hash()
    return snap


@pytest.fixture
def semantic_context():
    return SemanticContext(labels=(), metrics=(), semantic_version=1)


class MockQueryRunRepo:
    def __init__(self, runs: dict[str, dict]):
        self.runs = runs

    def get(self, query_id: str, user_id: str | None = None) -> dict | None:
        run = self.runs.get(query_id)
        if run is None:
            return None
        if user_id is not None and run.get("user_id") != user_id:
            return None
        return run


def test_resolve_followup_single_turn_success(catalog_snapshot, semantic_context):
    """Valid single completed parent resolves follow-up context with required references."""
    parent_ctx = RunContext(
        effective_question="Show all orders",
        canonical_sql_template="SELECT id, country FROM public.orders;",
        snapshot_hash=catalog_snapshot.snapshot_hash,
        policy_version=catalog_snapshot.policy_version,
        semantic_version=semantic_context.semantic_version,
        referenced_objects=(
            ObjectReference(namespace="public", table_name="orders", column_name="country", canonical_type="string", db_type="varchar(50)"),
        ),
    )
    runs = {
        "q1": {
            "id": "q1",
            "user_id": "user_1",
            "connection_id": "conn_1",
            "status": "completed",
            "question": "Show all orders",
            "canonical_sql": "SELECT id, country FROM public.orders;",
            "run_context_json": parent_ctx.model_dump_json(),
            "parent_query_id": None,
            "assumptions_json": json.dumps(["Direct projection"]),
        }
    }
    repo = MockQueryRunRepo(runs)

    ctx = resolve_followup_context(
        parent_query_id="q1",
        user_id="user_1",
        connection_id="conn_1",
        current_snapshot=catalog_snapshot,
        semantics=semantic_context,
        current_question="Only USA",
        max_tokens=2000,
        repo=repo,
    )

    assert isinstance(ctx, FollowUpContext)
    assert len(ctx.turns) == 1
    assert ctx.turns[0].query_id == "q1"
    assert ctx.turns[0].question == "Show all orders"
    assert "public.orders" in ctx.turns[0].sql
    assert len(ctx.required_references) == 1
    assert ctx.required_references[0].column_name == "country"
    assert "Show all orders" in ctx.formatted_text
    assert ctx.estimated_tokens <= 2000


def test_resolve_followup_bounds_at_five_ancestors(catalog_snapshot, semantic_context):
    """Lineage of six turns retains only the latest five ancestors in chronological order."""
    runs = {}
    prev_id = None
    for i in range(1, 7):
        qid = f"q{i}"
        p_ctx = RunContext(
            effective_question=f"Question {i}",
            canonical_sql_template=f"SELECT id FROM public.orders WHERE id = {i};",
            snapshot_hash=catalog_snapshot.snapshot_hash,
            policy_version=catalog_snapshot.policy_version,
            semantic_version=semantic_context.semantic_version,
        )
        runs[qid] = {
            "id": qid,
            "user_id": "user_1",
            "connection_id": "conn_1",
            "status": "completed",
            "question": f"Question {i}",
            "canonical_sql": f"SELECT id FROM public.orders WHERE id = {i};",
            "run_context_json": p_ctx.model_dump_json(),
            "parent_query_id": prev_id,
            "assumptions_json": "[]",
        }
        prev_id = qid

    repo = MockQueryRunRepo(runs)

    ctx = resolve_followup_context(
        parent_query_id="q6",
        user_id="user_1",
        connection_id="conn_1",
        current_snapshot=catalog_snapshot,
        semantics=semantic_context,
        current_question="Question 7",
        max_tokens=2000,
        repo=repo,
    )

    # 6 turns available, must retain exactly latest 5 (q2 -> q6)
    assert len(ctx.turns) == 5
    assert [t.query_id for t in ctx.turns] == ["q2", "q3", "q4", "q5", "q6"]


def test_resolve_followup_detects_cycles(catalog_snapshot, semantic_context):
    """Lineage cycles are detected and rejected."""
    ctx_json = RunContext(
        effective_question="Cyclic question",
        canonical_sql_template="SELECT 1;",
        snapshot_hash=catalog_snapshot.snapshot_hash,
        policy_version=1,
        semantic_version=1,
    ).model_dump_json()

    runs = {
        "q1": {"id": "q1", "user_id": "user_1", "connection_id": "conn_1", "status": "completed", "question": "q1", "canonical_sql": "SELECT 1;", "run_context_json": ctx_json, "parent_query_id": "q2", "assumptions_json": "[]"},
        "q2": {"id": "q2", "user_id": "user_1", "connection_id": "conn_1", "status": "completed", "question": "q2", "canonical_sql": "SELECT 1;", "run_context_json": ctx_json, "parent_query_id": "q1", "assumptions_json": "[]"},
    }
    repo = MockQueryRunRepo(runs)

    with pytest.raises(FollowUpInvalidParentError, match="cycle"):
        resolve_followup_context(
            parent_query_id="q1",
            user_id="user_1",
            connection_id="conn_1",
            current_snapshot=catalog_snapshot,
            semantics=semantic_context,
            current_question="Next",
            repo=repo,
        )


def test_resolve_followup_rejects_missing_foreign_and_incomplete(catalog_snapshot, semantic_context):
    """Missing parent (404), foreign parent (404), incomplete parent (422), wrong connection (422)."""
    runs = {
        "incomplete": {"id": "incomplete", "user_id": "user_1", "connection_id": "conn_1", "status": "executing", "question": "inc", "canonical_sql": None, "run_context_json": None, "parent_query_id": None},
        "wrong_conn": {"id": "wrong_conn", "user_id": "user_1", "connection_id": "other_conn", "status": "completed", "question": "wc", "canonical_sql": "SELECT 1;", "run_context_json": "{}", "parent_query_id": None},
        "foreign": {"id": "foreign", "user_id": "other_user", "connection_id": "conn_1", "status": "completed", "question": "f", "canonical_sql": "SELECT 1;", "run_context_json": "{}", "parent_query_id": None},
    }
    repo = MockQueryRunRepo(runs)

    # Missing -> 404
    with pytest.raises(FollowUpParentNotFoundError):
        resolve_followup_context("missing", "user_1", "conn_1", catalog_snapshot, semantic_context, "next", repo=repo)

    # Foreign -> 404
    with pytest.raises(FollowUpParentNotFoundError):
        resolve_followup_context("foreign", "user_1", "conn_1", catalog_snapshot, semantic_context, "next", repo=repo)

    # Incomplete -> 422
    with pytest.raises(FollowUpInvalidParentError, match="completed"):
        resolve_followup_context("incomplete", "user_1", "conn_1", catalog_snapshot, semantic_context, "next", repo=repo)

    # Wrong connection -> 422
    with pytest.raises(FollowUpInvalidParentError, match="connection"):
        resolve_followup_context("wrong_conn", "user_1", "conn_1", catalog_snapshot, semantic_context, "next", repo=repo)


def test_resolve_followup_rejects_drift_and_legacy(catalog_snapshot, semantic_context):
    """Physical snapshot, policy version, or semantic version drift raises FollowUpContextStale (409)."""
    # 1. Snapshot drift
    drifted_ctx = RunContext(
        effective_question="Old Q",
        canonical_sql_template="SELECT 1;",
        snapshot_hash="a" * 64,
        policy_version=catalog_snapshot.policy_version,
        semantic_version=semantic_context.semantic_version,
    )
    runs = {
        "drifted_snap": {"id": "drifted_snap", "user_id": "user_1", "connection_id": "conn_1", "status": "completed", "question": "q", "canonical_sql": "SELECT 1;", "run_context_json": drifted_ctx.model_dump_json(), "parent_query_id": None, "assumptions_json": "[]"},
        "legacy": {"id": "legacy", "user_id": "user_1", "connection_id": "conn_1", "status": "completed", "question": "leg", "canonical_sql": "SELECT 1;", "run_context_json": None, "parent_query_id": None, "assumptions_json": "[]"},
    }
    repo = MockQueryRunRepo(runs)

    with pytest.raises(FollowUpContextStale, match="snapshot"):
        resolve_followup_context("drifted_snap", "user_1", "conn_1", catalog_snapshot, semantic_context, "next", repo=repo)

    # 2. Legacy parent without context
    with pytest.raises(FollowUpContextStale, match="context"):
        resolve_followup_context("legacy", "user_1", "conn_1", catalog_snapshot, semantic_context, "next", repo=repo)


def test_resolve_followup_rejects_oversized_context(catalog_snapshot, semantic_context):
    """Context exceeding max_tokens budget raises FollowUpContextOversized using UTF-8 byte estimator."""
    ctx = RunContext(
        effective_question="Normal question with some detail",
        canonical_sql_template="SELECT id, country FROM public.orders WHERE country = 'USA';",
        snapshot_hash=catalog_snapshot.snapshot_hash,
        policy_version=catalog_snapshot.policy_version,
        semantic_version=semantic_context.semantic_version,
    )
    runs = {
        "q1": {"id": "q1", "user_id": "user_1", "connection_id": "conn_1", "status": "completed", "question": "q1", "canonical_sql": "SELECT 1;", "run_context_json": ctx.model_dump_json(), "parent_query_id": None, "assumptions_json": "[]"}
    }
    repo = MockQueryRunRepo(runs)

    # Set tight max_tokens of 20 (formatted history has ~100 bytes)
    with pytest.raises(FollowUpContextOversized, match="budget"):
        resolve_followup_context("q1", "user_1", "conn_1", catalog_snapshot, semantic_context, "next", max_tokens=20, repo=repo)
