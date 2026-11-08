"""Authorized follow-up conversation lineage and context resolution (Contract C08)."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from querylens.domain.analytics import ObjectReference, RunContext
from querylens.domain.schema import CatalogSnapshot
from querylens.pipeline.context import estimate_tokens
from querylens.semantics.versions import SemanticContext


class FollowUpLineageError(Exception):
    """Base exception for follow-up lineage errors."""

    pass


class FollowUpParentNotFoundError(FollowUpLineageError):
    """Raised when parent query is missing or not owned by user."""

    pass


class FollowUpInvalidParentError(FollowUpLineageError):
    """Raised when parent query is incomplete, cyclic, or on a different connection."""

    pass


class FollowUpContextStale(FollowUpLineageError):
    """Raised when catalog snapshot, policy, or semantic version drifted since parent query."""

    pass


class FollowUpContextOversized(FollowUpLineageError):
    """Raised when follow-up conversation history exceeds maximum token budget."""

    pass


@dataclass(frozen=True)
class FollowUpTurn:
    query_id: str
    question: str
    sql: str
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class FollowUpContext:
    turns: tuple[FollowUpTurn, ...]
    latest_context: RunContext
    required_references: tuple[ObjectReference, ...]
    formatted_text: str
    estimated_tokens: int


def resolve_followup_context(
    parent_query_id: str,
    user_id: str,
    connection_id: str,
    current_snapshot: CatalogSnapshot,
    semantics: SemanticContext,
    current_question: str,
    max_tokens: int = 2000,
    repo: Any | None = None,
) -> FollowUpContext:
    """Traverse and authorize ancestry lineage, checking drift and token budgets."""
    if repo is None:
        from querylens.persistence.repositories.query_runs import QueryRunRepository

        repo = QueryRunRepository()

    current_id: str | None = parent_query_id
    collected_turns: list[FollowUpTurn] = []
    visited_ids: set[str] = set()
    immediate_parent_context: RunContext | None = None

    while current_id and len(collected_turns) < 10:
        if current_id in visited_ids:
            raise FollowUpInvalidParentError(f"Detected cycle in follow-up query lineage at {current_id}")
        visited_ids.add(current_id)

        run = repo.get(current_id, user_id=user_id)
        if run is None:
            if not collected_turns:
                raise FollowUpParentNotFoundError(f"Parent query '{current_id}' not found")
            break

        if run.get("user_id") != user_id:
            if not collected_turns:
                raise FollowUpParentNotFoundError(f"Parent query '{current_id}' does not belong to user")
            break

        if run.get("connection_id") != connection_id:
            if not collected_turns:
                raise FollowUpInvalidParentError(
                    f"Parent query '{current_id}' connection mismatch: {run.get('connection_id')} != {connection_id}"
                )
            break

        if run.get("status") != "completed":
            if not collected_turns:
                raise FollowUpInvalidParentError(
                    f"Parent query '{current_id}' must be completed, but is '{run.get('status')}'"
                )
            break

        ctx_raw = run.get("run_context_json")
        if not ctx_raw:
            if not collected_turns:
                raise FollowUpContextStale(f"Parent query '{current_id}' lacks modern analytics context")
            break

        try:
            if isinstance(ctx_raw, str):
                run_ctx = RunContext.model_validate_json(ctx_raw)
            else:
                run_ctx = RunContext.model_validate_json(json.dumps(ctx_raw))
        except Exception as exc:
            if not collected_turns:
                raise FollowUpContextStale(f"Failed to parse parent query context: {exc}") from exc
            break

        if not collected_turns:
            immediate_parent_context = run_ctx
            if run_ctx.snapshot_hash != current_snapshot.snapshot_hash:
                raise FollowUpContextStale("Catalog snapshot changed since parent query was run")
            if run_ctx.policy_version != current_snapshot.policy_version:
                raise FollowUpContextStale("Security policy changed since parent query was run")
            if run_ctx.semantic_version != semantics.semantic_version:
                raise FollowUpContextStale("Semantic definitions changed since parent query was run")

        assumptions: tuple[str, ...] = ()
        if run.get("assumptions_json"):
            try:
                raw_assump = json.loads(run["assumptions_json"])
                if isinstance(raw_assump, list):
                    assumptions = tuple(str(a) for a in raw_assump)
            except Exception:
                pass

        turn = FollowUpTurn(
            query_id=run["id"],
            question=run_ctx.effective_question,
            sql=run.get("canonical_sql") or run_ctx.canonical_sql_template,
            assumptions=assumptions,
        )
        collected_turns.append(turn)
        current_id = run.get("parent_query_id")

    if immediate_parent_context is None:
        raise FollowUpParentNotFoundError(f"Parent query '{parent_query_id}' context could not be loaded")

    chronological_turns = list(reversed(collected_turns))
    if len(chronological_turns) > 5:
        chronological_turns = chronological_turns[-5:]

    lines = ["FOLLOW-UP CONVERSATION HISTORY:"]
    for idx, t in enumerate(chronological_turns, 1):
        lines.append(f"Turn {idx}:")
        lines.append(f"Question: {t.question}")
        lines.append(f"SQL: {t.sql}")
        if t.assumptions:
            lines.append(f"Assumptions: {', '.join(t.assumptions)}")
    formatted_text = "\n".join(lines)

    tokens = estimate_tokens(formatted_text)
    if tokens > max_tokens:
        raise FollowUpContextOversized(
            f"Follow-up conversation context ({tokens} tokens) exceeds maximum budget ({max_tokens} tokens)"
        )

    return FollowUpContext(
        turns=tuple(chronological_turns),
        latest_context=immediate_parent_context,
        required_references=immediate_parent_context.referenced_objects,
        formatted_text=formatted_text,
        estimated_tokens=tokens,
    )
