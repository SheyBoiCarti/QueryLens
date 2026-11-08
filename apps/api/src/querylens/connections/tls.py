"""Certificate handling shared by source connection factories."""

from contextlib import contextmanager
import os
import ssl
import tempfile
from collections.abc import Iterator

import certifi


def mysql_tls_context(ca_cert: str | None = None) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    if ca_cert:
        context.load_verify_locations(cadata=ca_cert)
    return context


@contextmanager
def postgres_ca_file(ca_cert: str | None) -> Iterator[str]:
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
