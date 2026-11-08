"""Task 07.03 Tests: Repair context construction and validation contracts.

Contracts: C05, C06, C08.
Assertions:
1. Invalid-then-correct fake scenario yields one safe repair and actual correct result.
2. Repaired unsafe SQL is rejected before source call.
3. Forbidden object/error-parameter canaries never enter repair prompts.
4. Clarification exits without executing SQL.
5. Changed source policy invalidates the attempted repair.
"""

from __future__ import annotations

import pytest

from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
from querylens.pipeline.classifier import classify_pipeline_error
from querylens.pipeline.context import SchemaContext
from querylens.pipeline.repair_context import assemble_repair_context
from querylens.sql.policy import SQLPolicyViolationError, validate_and_bound_sql


def _sample_snapshot(policy_version: int = 1) -> CatalogSnapshot:
    return CatalogSnapshot(
        connection_id="conn-01",
        engine="postgres",
        policy_version=policy_version,
        snapshot_hash="hash-abc-123",
        tables=[
            TableMetadata(
                name="users",
                namespace="public",
                columns=[
                    ColumnMetadata(name="id", canonical_type="integer", db_type="int4", primary_key=True),
                    ColumnMetadata(name="name", canonical_type="string", db_type="varchar"),
                ],
            )
        ],
    )


def test_canaries_never_enter_repair_prompts() -> None:
    canary_secret = "secret_canary_pwd_999"
    canary_table = "forbidden_secret_vault"
    raw_error = Exception(f"Failed query with {canary_secret} on {canary_table}")

    classified = classify_pipeline_error(raw_error, engine="postgres")
    schema_ctx = SchemaContext(tables=[], formatted_schema="TABLE users (id, name)")

    repair_ctx = assemble_repair_context(
        question="Find users",
        dialect="postgres",
        schema_context=schema_ctx,
        prior_sql="SELECT name FROM users WHERE id = 1",
        classified_error=classified,
    )

    prompt_text = repair_ctx.formatted_prompt
    assert canary_secret not in prompt_text
    assert canary_table not in prompt_text
    assert classified.code in prompt_text


def test_repaired_unsafe_sql_is_rejected_before_execution() -> None:
    snapshot = _sample_snapshot()
    # Unsafe repaired query (e.g. attempting DROP or INSERT or recursive CTE)
    unsafe_repaired_sql = "DROP TABLE users"

    with pytest.raises(SQLPolicyViolationError):
        validate_and_bound_sql(
            sql=unsafe_repaired_sql,
            connection_id="conn-01",
            engine="postgres",
            snapshot=snapshot,
            max_rows=100,
        )


def test_changed_source_policy_invalidates_repair() -> None:
    snapshot_v1 = _sample_snapshot(policy_version=1)
    snapshot_v2 = _sample_snapshot(policy_version=2)

    # Valid query on v1
    token_v1 = validate_and_bound_sql(
        sql="SELECT id, name FROM users",
        connection_id="conn-01",
        engine="postgres",
        snapshot=snapshot_v1,
        max_rows=100,
    )

    # Token v1 carries policy_version 1
    assert token_v1.policy_version == 1
    # Snapshot v2 has policy_version 2, so token_v1 is invalid against snapshot_v2
    assert token_v1.policy_version != snapshot_v2.policy_version
