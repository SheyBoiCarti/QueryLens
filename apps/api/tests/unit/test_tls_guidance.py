"""Certificate errors should explain how to configure provider trust."""

import pytest

from querylens.connections.mysql import MySQLAdapter
from querylens.connections.postgres import PostgresAdapter


@pytest.mark.parametrize("adapter", [MySQLAdapter, PostgresAdapter])
@pytest.mark.parametrize("error", [
    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain",
    "SSL error: certificate verify failed",
])
def test_certificate_failure_guidance(adapter, error, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError(error + " secret-password")

    monkeypatch.setattr(adapter, "connect", fail)
    success, version, message = adapter.test_connection("db.example.com", 28173, "db", "user", "secret-password")
    assert not success
    assert version == ""
    assert "Custom CA certificate" in message
    assert "ca.pem" in message
    assert "secret-password" not in message


@pytest.mark.parametrize("adapter", [MySQLAdapter, PostgresAdapter])
def test_other_failures_do_not_suggest_certificate_fix(adapter, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Connection refused")

    monkeypatch.setattr(adapter, "connect", fail)
    success, _, message = adapter.test_connection("db.example.com", 28173, "db", "user", "password")
    assert not success
    assert "Connection refused" in message
    assert "Custom CA certificate" not in message
