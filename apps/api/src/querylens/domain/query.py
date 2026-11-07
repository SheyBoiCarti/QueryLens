"""ValidatedQuery capability token and execution models (Contracts C06, C07)."""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Any


@dataclasses.dataclass(frozen=True)
class ValidatedQuery:
    """Immutable internal capability token minted only by the AST validator (Contract C06).
    
    Contains canonical bounded SQL, fingerprint, connection binding, and current policy snapshot.
    Never deserialized from API inputs.
    """
    connection_id: str
    engine: str
    policy_version: int
    snapshot_hash: str
    canonical_sql: str
    sql_fingerprint: str
    permitted_identifiers: tuple[str, ...]
    max_rows: int
    truncated: bool = False

    @classmethod
    def create(
        cls,
        connection_id: str,
        engine: str,
        policy_version: int,
        snapshot_hash: str,
        canonical_sql: str,
        permitted_identifiers: list[str],
        max_rows: int,
    ) -> ValidatedQuery:
        """Mint a ValidatedQuery token."""
        fp = hashlib.sha256(canonical_sql.strip().encode("utf-8")).hexdigest()
        return cls(
            connection_id=connection_id,
            engine=engine,
            policy_version=policy_version,
            snapshot_hash=snapshot_hash,
            canonical_sql=canonical_sql.strip(),
            sql_fingerprint=fp,
            permitted_identifiers=tuple(sorted(permitted_identifiers)),
            max_rows=max_rows,
        )


@dataclasses.dataclass
class QueryResult:
    columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    execution_time_ms: int
