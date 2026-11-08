"""Focused remediation regressions. These specifications were not executed."""

import hashlib
import hmac
import ssl

import pytest

from querylens.auth.dependencies import derive_csrf_token
from querylens.connections.mysql import VerifiedMySQLConnection
from querylens.execution.serializer import serialize_result_set
from querylens.jobs.admission import AdmissionController, AdmissionOverloadError
from querylens.jobs.results import ResultCache


def test_duplicate_column_names_cannot_overwrite_another_value():
    columns, rows, truncated = serialize_result_set(
        [("id", "int"), ("id", "int"), ("id_2", "int")],
        [(1, 2, 3)],
        10,
    )
    assert [column["name"] for column in columns] == ["id", "id_3", "id_2"]
    assert rows == [{"id": "1", "id_3": "2", "id_2": "3"}]
    assert truncated is False


def test_cache_replacement_and_connection_revocation_release_budget():
    cache = ResultCache(max_bytes=5000)
    cache.put("query", "snapshot", [], [{"value": "first"}], connection_id="source")
    cache.put("query", "snapshot", [], [{"value": "replacement"}], connection_id="source")
    assert cache.get("query") == ([], [{"value": "replacement"}])
    cache.evict_connection("source")
    assert cache.get("query") is None
    assert cache._total_bytes == 0


def test_csrf_is_bound_to_the_session_without_process_memory():
    expected = hmac.new(b"session-secret", b"querylens-csrf-v1", hashlib.sha256).hexdigest()
    assert derive_csrf_token("session-secret") == expected
    assert derive_csrf_token("another-session") != expected


def test_mysql_refuses_tls_downgrade_before_authentication():
    # Never connects: the server capability check must fail before any socket IO.
    connection = VerifiedMySQLConnection(defer_connect=True, ssl=ssl.create_default_context())
    connection.server_capabilities = 0
    with pytest.raises(Exception, match="does not offer required TLS"):
        connection._request_authentication()


@pytest.mark.asyncio
async def test_waiting_jobs_and_active_leases_are_bounded_and_released():
    controller = AdmissionController(global_active_limit=1, global_waiting_limit=1, per_user_waiting_limit=1)
    first = controller.reserve("user", "source")
    await first.activate(1)
    second = controller.reserve("user", "source")
    with pytest.raises(AdmissionOverloadError):
        controller.reserve("user", "source")
    second.release()
    first.release()
    first.release()
    assert controller._active_global == 0
    assert controller._waiting_global == 0
