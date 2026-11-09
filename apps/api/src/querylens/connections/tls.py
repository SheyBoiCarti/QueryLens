"""Certificate handling shared by source connection factories."""

from contextlib import contextmanager
import os
import ssl
import tempfile
from collections.abc import Iterator

import certifi

from querylens.connections.models import TLSMode


def mysql_tls_context(ca_cert: str | None = None, tls_mode: TLSMode = "verify-full") -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    if tls_mode == "require":
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    elif tls_mode == "verify-ca":
        context.check_hostname = False
    if ca_cert and tls_mode != "require":
        context.load_verify_locations(cadata=ca_cert)
    return context


@contextmanager
def postgres_ca_file(ca_cert: str | None, tls_mode: TLSMode = "verify-full") -> Iterator[str]:
    if tls_mode == "require":
        # libpq upgrades require to CA verification if its default root.crt exists.
        # An explicitly absent file preserves the requested encryption-only mode.
        with tempfile.TemporaryDirectory(prefix="querylens-tls-") as directory:
            yield os.path.join(directory, "no-root.pem")
        return
    if not ca_cert:
        yield certifi.where()
        return
    descriptor, path = tempfile.mkstemp(prefix="querylens-ca-", suffix=".pem")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(ca_cert)
        yield path
    finally:
        os.unlink(path)


def certificate_failure_hint(message: str) -> str:
    """Explain certificate trust failures without weakening verification."""
    if "certificate verify failed" not in message.lower() and "certificate_verify_failed" not in message.lower():
        return ""
    return (
        " Add your database provider's CA certificate (PEM) in Custom CA certificate "
        "and use the provider's DNS hostname. For Aiven, download ca.pem from "
        "the service Overview page. Use the encryption setting from your provider connection string, or "
        "supply its CA certificate to verify the server."
    )
