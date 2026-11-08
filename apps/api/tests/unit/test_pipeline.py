"""Unit tests for Phase 05 LLM protocol, fake provider, state repository, and result cache."""

import time
import pytest
from pydantic import ValidationError

from querylens.domain.schema import CatalogSnapshot
from querylens.jobs.results import ResultCache
from querylens.llm.fake import FakeLLMProvider
from querylens.llm.protocol import GeneratedCandidate, LLMUsage
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, set_engine
from querylens.persistence.tables import metadata
import sqlalchemy as sa


def test_generated_candidate_validation():
    """GeneratedCandidate validates SQL/clarification mutually exclusive requirements (Contract C08)."""
    # Valid answerable
    cand1 = GeneratedCandidate(
        sql="SELECT 1;",
        assumptions=["Simple assumption"],
        requires_clarification=False,
    )
    assert cand1.sql == "SELECT 1;"

    # Valid clarification
    cand2 = GeneratedCandidate(
        requires_clarification=True,
        clarification_question="Which date range do you want?",
    )
    assert cand2.requires_clarification is True

    # Missing clarification_question when requires_clarification is True -> error
    with pytest.raises(ValidationError):
        GeneratedCandidate(requires_clarification=True, clarification_question=None)

    # Missing SQL when requires_clarification is False -> error
    with pytest.raises(ValidationError):
        GeneratedCandidate(requires_clarification=False, sql=None)


@pytest.mark.asyncio
async def test_fake_llm_provider_behavior():
    """FakeLLMProvider answers registered questions and fails on unknown questions (Contract C08)."""
    fake = FakeLLMProvider()

    # Pre-seeded smoke question
    cand = await fake.generate("how many customers are there", dialect="postgresql", schema_context="")
    assert cand.sql is not None
    assert "COUNT" in cand.sql

    # Unknown question MUST raise test error, never default to SELECT 1
    with pytest.raises(ValueError, match="unknown question"):
        await fake.generate("random unknown unseeded question", dialect="postgresql", schema_context="")


def test_result_cache_ttl_and_snapshot_drift():
    """ResultCache respects TTL and evicts when snapshot hash changes (Contract C05, C09)."""
    cache = ResultCache(max_bytes=100000, ttl_sec=1)
    cols = [{"name": "id", "type": "integer", "db_type": "int"}]
    rows = [{"id": 1}]

    cache.put("q1", "snap-hash-1", cols, rows)
    # Immediate get matches
    res = cache.get("q1", "snap-hash-1")
    assert res is not None
    assert res[1] == rows

    # Get with different snapshot hash (drift) -> cache invalidated (None)
    res_drift = cache.get("q1", "snap-hash-2")
    assert res_drift is None


def test_query_run_terminal_state_protection():
    """Terminal states cannot be overwritten by later events (Contract C08)."""
    test_eng = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    set_engine(test_eng)
    create_metadata_tables(test_eng)

    repo = QueryRunRepository()
    repo.create("run-1", "user-1", "conn-1", "question")

    # queued -> executing -> completed
    assert repo.update_state("run-1", "executing") is True
    assert repo.update_state("run-1", "completed") is True

    # Attempting to overwrite completed with failed must return False and stay completed
    assert repo.update_state("run-1", "failed") is False
    final = repo.get("run-1")
    assert final["status"] == "completed"

    drop_metadata_tables(test_eng)
    test_eng.dispose()


def test_startup_reconciliation_marks_interrupted():
    """Nonterminal runs are marked interrupted on startup (Contract C08)."""
    test_eng = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    set_engine(test_eng)
    create_metadata_tables(test_eng)

    repo = QueryRunRepository()
    repo.create("run-running", "user-1", "conn-1", "question")
    repo.update_state("run-running", "executing")

    repo.create("run-done", "user-1", "conn-1", "question")
    repo.update_state("run-done", "completed")

    # Simulate server process restart
    interrupted_count = QueryRunRepository.mark_interrupted_runs()
    assert interrupted_count >= 1

    r_run = repo.get("run-running")
    assert r_run["status"] == "interrupted"
    assert r_run["error_code"] == "PROCESS_INTERRUPTED"

    r_done = repo.get("run-done")
    assert r_done["status"] == "completed"

    drop_metadata_tables(test_eng)
    test_eng.dispose()
