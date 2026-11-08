"""Join path expansion for ranked context tables (Contracts C05, C10)."""

from __future__ import annotations

from querylens.domain.schema import CatalogSnapshot, TableMetadata
from querylens.schema.graph import SchemaGraph


def expand_join_paths(
    ranked_tables: list[TableMetadata],
    snapshot: CatalogSnapshot,
    max_extra_tables: int = 3,
) -> list[TableMetadata]:
    """Find intermediate tables required to connect isolated ranked tables."""
    if len(ranked_tables) < 2 or max_extra_tables <= 0:
        return ranked_tables

    graph = SchemaGraph(snapshot)
    tables_by_name = {graph.node_names[(table.namespace, table.name)]: table for table in snapshot.tables}
    included_names = {graph.node_names[(table.namespace, table.name)] for table in ranked_tables}
    extra_tables: list[TableMetadata] = []

    # Check pairs of ranked tables
    for i in range(len(ranked_tables)):
        for j in range(i + 1, len(ranked_tables)):
            t_a = f"{ranked_tables[i].namespace}.{ranked_tables[i].name}"
            t_b = f"{ranked_tables[j].namespace}.{ranked_tables[j].name}"

            status, path = graph.resolve_join_path(t_a, t_b)
            if status in ("unique", "ambiguous") and path:
                # Add bridge tables along path
                for edge in path:
                    for node_name in [edge.source_table, edge.target_table]:
                        if node_name not in included_names and node_name in tables_by_name:
                            included_names.add(node_name)
                            extra_tables.append(tables_by_name[node_name])
                            if len(extra_tables) >= max_extra_tables:
                                return ranked_tables + extra_tables

    return ranked_tables + extra_tables
