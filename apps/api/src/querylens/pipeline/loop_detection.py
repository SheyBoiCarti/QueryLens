"""Loop and repetition detection for query repair (Contracts C07, C08)."""

from __future__ import annotations

import hashlib
import re
import sqlglot


def candidate_fingerprint(sql: str) -> str:
    """Generate canonical SQL candidate fingerprint preserving literal case."""
    try:
        # sqlglot ast preserves string literal case and quoted identifiers
        ast = sqlglot.parse_one(sql)
        canonical = ast.sql()
    except Exception:
        # Fallback to whitespace normalization preserving literal case
        canonical = re.sub(r"\s+", " ", sql).strip()

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LoopDetector:
    """Run-scoped detector for repeated candidates and consecutive error loops."""

    def __init__(self) -> None:
        self._seen_fingerprints: set[str] = set()
        self._last_error_signature: str | None = None

    def check_candidate(self, sql: str) -> bool:
        """Returns True if candidate is new, False if repeated candidate detected."""
        fp = candidate_fingerprint(sql)
        if fp in self._seen_fingerprints:
            return False
        self._seen_fingerprints.add(fp)
        return True

    def check_error_signature(self, signature: str) -> bool:
        """Returns True if error signature is not repeated consecutively, False otherwise."""
        if signature == self._last_error_signature:
            return False
        self._last_error_signature = signature
        return True
