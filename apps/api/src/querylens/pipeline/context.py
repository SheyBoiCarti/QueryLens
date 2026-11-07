"""Schema context assembly and input token bounding (Contracts C05, C07, C08)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from querylens.domain.schema import CatalogSnapshot

MAX_INPUT_TOKENS = 6000


@dataclass(frozen=True)
class SchemaContext:
    """Bounded schema context for LLM prompt assembly."""

    tables: list[Any] = field(default_factory=list)
    formatted_schema: str = ""



def estimate_tokens(text: str) -> int:
    """Approximate token count (1 token ~= 4 characters)."""
    return max(1, len(text) // 4)


def build_schema_context(snapshot: CatalogSnapshot, max_tokens: int = MAX_INPUT_TOKENS) -> str:
    """Build serialized schema context with strict boundaries and token bounds."""
    lines = [
        f"TARGET DATABASE ENGINE: {snapshot.engine.upper()}",
        f"CATALOG SNAPSHOT HASH: {snapshot.snapshot_hash}",
        "VISIBLE TABLES AND COLUMNS:",
    ]

    for table in snapshot.tables:
        col_strs = []
        for c in table.columns:
            pk_badge = " [PK]" if c.primary_key else ""
            col_strs.append(f"{c.name} ({c.canonical_type}{pk_badge})")

        lines.append(f"- TABLE {table.name} ({table.namespace}):")
        lines.append(f"  Columns: {', '.join(col_strs)}")

        if table.foreign_keys:
            fk_strs = []
            for fk in table.foreign_keys:
                src = ", ".join(fk.source_columns)
                tgt = ", ".join(fk.target_columns)
                fk_strs.append(f"({src}) -> {fk.target_table}({tgt})")
            lines.append(f"  Relationships: {'; '.join(fk_strs)}")

    full_context = "\n".join(lines)

    # Check token bound
    tokens = estimate_tokens(full_context)
    if tokens > max_tokens:
        # Deterministically truncate tables that exceed token budget
        truncated_lines = lines[:10]
        truncated_lines.append("... [Schema context bounded due to token limits]")
        return "\n".join(truncated_lines)

    return full_context
