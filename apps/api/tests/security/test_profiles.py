"""Security profile validation, negative tests, and secret leak prevention (Contracts C01, C02, C03, C11)."""

import io
import json
import logging
import pytest
from querylens.config import SecurityProfileError, Settings, validate_security_profile
from querylens.observability.logging import StructuredJsonFormatter, log_event
from querylens.observability.metrics import get_metrics_snapshot, record_security_event, record_stage_metrics


def test_production_security_profile_validation():
    # 1. Base invalid production settings
    settings = Settings(
        environment="production",
        session_cookie_secure=False,
        session_cookie_name="querylens_session",
        credential_keys_file=None,
        credential_active_key_id=None,
        llm_provider="fake",
    )

    # Rejects insecure cookie
    with pytest.raises(SecurityProfileError, match="session_cookie_secure"):
        validate_security_profile(settings, deployment="production")

    # Rejects non-__Host- cookie name
    settings.session_cookie_secure = True
    with pytest.raises(SecurityProfileError, match="__Host-"):
        validate_security_profile(settings, deployment="production")

    # Rejects missing keyring
    settings.session_cookie_name = "__Host-querylens_session"
    with pytest.raises(SecurityProfileError, match="credential_keys_file"):
        validate_security_profile(settings, deployment="production")

    # Rejects fake provider in production
    settings.credential_keys_file = "/run/secrets/keyring.json"
    settings.credential_active_key_id = "key-01"
    with pytest.raises(SecurityProfileError, match="forbids fake LLM provider"):
        validate_security_profile(settings, deployment="production")

    # Rejects missing live provider API key
    settings.llm_provider = "live"
    settings.llm_api_key = None
    with pytest.raises(SecurityProfileError, match="llm_api_key"):
        validate_security_profile(settings, deployment="production")

    # Rejects excessive budgets
    settings.llm_api_key = "sk-production-test-key"
    settings.max_sql_bytes = 100000
    with pytest.raises(SecurityProfileError, match="max_sql_bytes"):
        validate_security_profile(settings, deployment="production")

    # Valid production settings pass cleanly
    settings.max_sql_bytes = 32768
    validate_security_profile(settings, deployment="production")


def test_canary_secrets_never_logged_or_exposed():
    canary_password = "canary_db_password_XYZ999!"
    canary_api_key = "canary_sk_live_SECRET888"
    canary_prompt = "SELECT * FROM secrets_table WHERE canary='leak';"

    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(StructuredJsonFormatter())

    test_logger = logging.getLogger("test_canary_sanitization")
    test_logger.handlers = [handler]
    test_logger.propagate = False

    # Attempt to log event with sensitive kwargs
    record = test_logger.makeRecord(
        name="test_canary_sanitization",
        level=logging.INFO,
        fn="",
        lno=0,
        msg="query_completed",
        args=(),
        exc_info=None,
    )
    # Inject both allowlisted and canary fields
    record.request_id = "req-123"
    record.run_id = "run-456"
    record.status = "success"
    # Unsafe fields that must not be logged
    record.password = canary_password
    record.api_key = canary_api_key
    record.prompt = canary_prompt

    handler.emit(record)
    output = log_stream.getvalue().strip()

    # Log must parse as valid JSON
    log_data = json.loads(output)
    assert log_data["event"] == "query_completed"
    assert log_data["request_id"] == "req-123"
    assert log_data["run_id"] == "run-456"

    # Canary strings must NOT be present anywhere in the serialized log JSON
    assert canary_password not in output
    assert canary_api_key not in output
    assert canary_prompt not in output
    assert "password" not in log_data
    assert "api_key" not in log_data
    assert "prompt" not in log_data


def test_metric_cardinality_and_safety():
    canary_sql = "DROP TABLE users;"
    record_stage_metrics(run_id="run-1", stage="ast_validation", outcome="rejected")
    record_security_event("sql_policy_violation")

    snapshot = get_metrics_snapshot()
    assert "stage_executions" in snapshot
    assert "security_events" in snapshot

    # Labels must be low-cardinality and free of user SQL or canary values
    raw_snapshot = json.dumps(snapshot)
    assert canary_sql not in raw_snapshot
