"""ValidatedQuery capability token and execution models (Contracts C06, C07)."""

from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
import hashlib
import json
from typing import Any

from querylens.domain.analytics import BoundParameter, ResolvedParameters


def compute_token_fingerprint(
    canonical_sql: str,
    bindings: tuple[BoundParameter, ...],
    connection_id: str,
    engine: str,
    policy_version: int,
    snapshot_hash: str,
    permitted_identifiers: tuple[str, ...],
    max_rows: int,
) -> str:
    """Deterministic typed fingerprint covering SQL, bindings, connection, engine, policy, snapshot, identifiers, and limits."""
    binding_items = []
    for b in bindings:
        val = b.value
        if isinstance(val, (dt.datetime, dt.date)):
            val_repr = val.isoformat()
        elif isinstance(val, Decimal):
            val_repr = str(val)
        elif isinstance(val, bool):
            val_repr = "true" if val else "false"
        elif isinstance(val, (int, float)):
            val_repr = str(val)
        else:
            val_repr = str(val)
        binding_items.append({"name": b.name, "type": b.scalar_type, "val": val_repr})

    payload = {
        "sql": canonical_sql.strip(),
        "bindings": binding_items,
        "connection_id": connection_id,
        "engine": engine,
        "policy_version": policy_version,
        "snapshot_hash": snapshot_hash,
        "permitted_identifiers": sorted(permitted_identifiers),
        "max_rows": max_rows,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    bindings: tuple[BoundParameter, ...] = ()
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
        bindings: tuple[BoundParameter, ...] = (),
    ) -> ValidatedQuery:
        """Mint a ValidatedQuery token."""
        fp = compute_token_fingerprint(
            canonical_sql=canonical_sql.strip(),
            bindings=bindings,
            connection_id=connection_id,
            engine=engine,
            policy_version=policy_version,
            snapshot_hash=snapshot_hash,
            permitted_identifiers=tuple(sorted(permitted_identifiers)),
            max_rows=max_rows,
        )
        return cls(
            connection_id=connection_id,
            engine=engine,
            policy_version=policy_version,
            snapshot_hash=snapshot_hash,
            canonical_sql=canonical_sql.strip(),
            sql_fingerprint=fp,
            permitted_identifiers=tuple(sorted(permitted_identifiers)),
            max_rows=max_rows,
            bindings=bindings,
        )


@dataclasses.dataclass
class QueryResult:
    columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    execution_time_ms: int


@dataclasses.dataclass(frozen=True)
class ValidatedArtifact:
    """Authorized SQL provenance, before server fetch-limit injection."""

    token: ValidatedQuery
    template_sql: str
    author_limit: int | None
    resolved_parameters: ResolvedParameters = dataclasses.field(default_factory=ResolvedParameters)
