"""Foreign key relationship graph builder and path resolution (Contracts C05, C10)."""

from __future__ import annotations

from collections import deque
from typing import NamedTuple
from querylens.domain.schema import CatalogSnapshot, ForeignKeyConstraint


class GraphEdge(NamedTuple):
    source_table: str
    target_table: str
    source_columns: list[str]
    target_columns: list[str]
    is_reverse: bool = False


class SchemaGraph:
    """In-memory relationship graph supporting bi-directional traversal and path resolution."""

    def __init__(self, catalog: CatalogSnapshot) -> None:
        self.catalog = catalog
        self.adj: dict[str, list[GraphEdge]] = {}
        self._build_graph()

    def _build_graph(self) -> None:
        for table in self.catalog.tables:
            t_name = table.name
            self.adj.setdefault(t_name, [])

            for fk in table.foreign_keys:
                # Forward edge (table -> target)
                forward = GraphEdge(
                    source_table=t_name,
                    target_table=fk.target_table,
                    source_columns=fk.source_columns,
                    target_columns=fk.target_columns,
                    is_reverse=False,
                )
                self.adj[t_name].append(forward)

                # Reverse edge (target -> table)
                reverse = GraphEdge(
                    source_table=fk.target_table,
                    target_table=t_name,
                    source_columns=fk.target_columns,
                    target_columns=fk.source_columns,
                    is_reverse=True,
                )
                self.adj.setdefault(fk.target_table, []).append(reverse)

    def find_paths(self, start_table: str, target_table: str, max_depth: int = 5) -> list[list[GraphEdge]]:
        """Find all simple paths between start and target tables up to max_depth."""
        if start_table == target_table:
            return []

        all_paths: list[list[GraphEdge]] = []
        queue: deque[tuple[str, list[GraphEdge], set[str]]] = deque([(start_table, [], {start_table})])

        while queue:
            curr, path, visited = queue.popleft()
            if len(path) >= max_depth:
                continue

            for edge in self.adj.get(curr, []):
                nxt = edge.target_table
                if nxt in visited:
                    continue

                new_path = path + [edge]
                if nxt == target_table:
                    all_paths.append(new_path)
                else:
                    queue.append((nxt, new_path, visited | {nxt}))

        # Sort paths by length
        all_paths.sort(key=len)
        return all_paths

    def resolve_join_path(self, table_a: str, table_b: str) -> tuple[str, list[GraphEdge] | None]:
        """Resolve join path between two tables.
        
        Returns:
            ("unique", path) if exactly one shortest path exists.
            ("ambiguous", paths) if multiple paths of equal shortest length exist.
            ("disconnected", None) if no path exists.
        """
        paths = self.find_paths(table_a, table_b)
        if not paths:
            return "disconnected", None

        min_len = len(paths[0])
        shortest = [p for p in paths if len(p) == min_len]
        if len(shortest) > 1:
            return "ambiguous", shortest[0]  # flag as ambiguous

        return "unique", shortest[0]
