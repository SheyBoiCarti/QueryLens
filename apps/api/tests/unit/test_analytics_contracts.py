"""Unit tests for Everyday Analytics contracts and OpenAPI parity (Task 13).

Validates:
1. Deterministic live OpenAPI schema matches packages/contracts/openapi.json byte-for-byte.
2. Shared contract fixtures (packages/contracts/fixtures/everyday_analytics.json)
   validate against backend Pydantic models.
3. Exact constraints, enums, and requiredness on analytics contracts.
"""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from querylens.config import Settings, set_settings
from querylens.main import create_app
from querylens.api.queries import (
    CreateQueryRequest,
    CreateSQLQueryRequest,
)
from querylens.api.query_schemas import (
    PublicRunCompleted,
    PublicRunFailed,
    PublicRunClarification,
    PublicRunCancelled,
    SavedQuestionCreateRequest,
    SavedQuestionRunRequest,
    SavedQuestionDetail,
)
from querylens.domain.presentation import PresentationMetadata
from querylens.sql.parameters import (
    ParameterDefinition,
)


@pytest.fixture(scope="module")
def repo_root():
    return Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def fixtures(repo_root):
    fixture_path = repo_root / "packages" / "contracts" / "fixtures" / "everyday_analytics.json"
    assert fixture_path.exists(), f"Missing fixture file: {fixture_path}"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_openapi_schema_matches_checked_in(repo_root):
    """Live FastAPI OpenAPI schema must match checked-in openapi.json without drift."""
    settings = Settings(_env_file=None, environment="test")
    set_settings(settings)
    app = create_app(settings)

    live_schema = app.openapi()
    formatted_live = json.dumps(live_schema, indent=2, sort_keys=True) + "\n"

    openapi_path = repo_root / "packages" / "contracts" / "openapi.json"
    assert openapi_path.exists(), f"Missing openapi.json at {openapi_path}"

    with open(openapi_path, "r", encoding="utf-8") as f:
        checked_in = f.read()

    assert formatted_live == checked_in, (
        "Live OpenAPI schema does not match packages/contracts/openapi.json! "
        "Run `python scripts/export_schema.py` to update."
    )


def test_request_fixtures_validate_against_models(fixtures):
    """Request fixtures validate against API request models."""
    reqs = fixtures["requests"]

    # Natural Language
    nl_req = CreateQueryRequest.model_validate(reqs["nl_query"])
    assert nl_req.question == "Total sales by region for 2026"
    assert nl_req.connection_id == "conn-uuid-1"
    assert nl_req.max_rows == 100

    # Manual SQL
    sql_req = CreateSQLQueryRequest.model_validate(reqs["manual_sql"])
    assert "GROUP BY region" in sql_req.sql
    assert sql_req.source_query_id == "query-uuid-nl-1"

    # Follow-Up Query
    fu_req = CreateQueryRequest.model_validate(reqs["followup_query"])
    assert fu_req.parent_query_id == "query-uuid-nl-1"

    # Saved Question Create
    sq_create = SavedQuestionCreateRequest.model_validate(reqs["saved_question_create"])
    assert sq_create.title == "Regional Sales Summary"
    assert len(sq_create.parameters) == 1

    # Saved Question Run
    sq_run = SavedQuestionRunRequest.model_validate(reqs["saved_question_run"])
    assert sq_run.parameters["region_name"] == "EMEA"


def test_run_fixtures_validate_against_models(fixtures):
    """Run response fixtures validate against PublicRun models."""
    runs = fixtures["runs"]

    # Completed Run
    completed = PublicRunCompleted.model_validate_json(json.dumps(runs["completed"]))
    assert completed.status == "completed"
    assert completed.origin == "natural_language"
    assert completed.row_count == 2
    assert completed.results_available is True
    assert completed.presentation is not None
    assert completed.presentation.chart_type == "bar"

    # Failed Run
    failed = PublicRunFailed.model_validate_json(json.dumps(runs["failed"]))
    assert failed.status == "failed"
    assert failed.error_code == "POLICY_VIOLATION"

    # Clarification Run
    clarification = PublicRunClarification.model_validate_json(json.dumps(runs["clarification"]))
    assert clarification.status == "clarification_required"
    assert "revenue" in clarification.clarification_question

    # Cancelled Run
    cancelled = PublicRunCancelled.model_validate_json(json.dumps(runs["cancelled"]))
    assert cancelled.status == "cancelled"


def test_parameter_fixtures_validate_against_models(fixtures):
    """Parameter fixtures validate against parameter models."""
    params = fixtures["parameters"]

    cat = ParameterDefinition.model_validate(params["category"])
    assert cat.param_type == "category"
    assert cat.target.operator == "="
    assert cat.allowed_values == ("EMEA", "APAC", "AMER")

    dr = ParameterDefinition.model_validate(params["date_range"])
    assert dr.param_type == "date_range"
    assert dr.default_value == {"mode": "this_year"}

    rc = ParameterDefinition.model_validate(params["result_count"])
    assert rc.param_type == "result_count"
    assert rc.target is None
    assert rc.default_value == 50


def test_presentation_fixtures_validate_against_models(fixtures):
    """Presentation fixtures validate against PresentationMetadata."""
    pres = fixtures["presentations"]

    sv = PresentationMetadata.model_validate_json(json.dumps(pres["single_value"]))
    assert sv.chart_type == "single_value"
    assert sv.value == "$1,234,567"

    line = PresentationMetadata.model_validate_json(json.dumps(pres["line"]))
    assert line.chart_type == "line"
    assert line.x_column == "month"

    bar = PresentationMetadata.model_validate_json(json.dumps(pres["bar"]))
    assert bar.chart_type == "bar"
    assert bar.y_column == "total"

    tbl = PresentationMetadata.model_validate_json(json.dumps(pres["table"]))
    assert tbl.chart_type == "table"


def test_saved_question_fixture_validates_against_model(fixtures):
    """Saved question fixture validates against SavedQuestionDetail."""
    sq = SavedQuestionDetail.model_validate_json(json.dumps(fixtures["saved_question"]))
    assert sq.id == "saved-q-1"
    assert sq.revision == 1
    assert len(sq.parameters) == 1


def test_contract_negative_assertions():
    """Negative tests: verify that invalid enums and constraints are rejected."""
    # Invalid origin
    with pytest.raises(ValidationError):
        PublicRunCompleted.model_validate({
            "query_id": "q1",
            "connection_id": "c1",
            "status": "completed",
            "state_version": 1,
            "origin": "magic_generation",  # invalid
            "question": "q",
            "created_at": "2026-11-08T12:00:00Z",
            "updated_at": "2026-11-08T12:00:01Z",
            "dialect": "postgresql",
            "sql": "SELECT 1;",
            "assumptions": [],
            "warnings": [],
            "columns": [],
            "row_count": 0,
            "truncated": False,
            "results_available": True,
        })

    # Invalid chart_type
    with pytest.raises(ValidationError):
        PresentationMetadata.model_validate({
            "title": "Title",
            "explanation": "Exp",
            "chart_type": "pie_chart",  # not permitted
        })

    # Negative max_rows
    with pytest.raises(ValidationError):
        CreateQueryRequest.model_validate({
            "connection_id": "c1",
            "question": "q",
            "max_rows": -5,
        })
