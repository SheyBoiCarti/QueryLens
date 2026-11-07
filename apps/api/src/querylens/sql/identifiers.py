"""Identifier resolution and authorization checks against catalog snapshot (Contract C05, C06)."""

from __future__ import annotations

from sqlglot import exp
from querylens.domain.schema import CatalogSnapshot


class IdentifierPolicyError(Exception):
    """Raised when an unauthorized table or column is referenced."""
    pass


def resolve_identifiers(ast: exp.Expression, snapshot: CatalogSnapshot) -> list[str]:
    """Resolve and validate all table and column identifiers in AST.
    
    Returns:
        List of authorized physical identifiers referenced in query.
    """
    visible_tables: dict[str, set[str]] = {
        t.name.lower(): {c.name.lower() for c in t.columns}
        for t in snapshot.tables
    }

    # Track CTE names in query
    cte_names: set[str] = set()
    for cte in ast.find_all(exp.CTE):
        cte_alias = cte.alias_or_name.lower()
        cte_names.add(cte_alias)

    referenced_identifiers: set[str] = set()

    # 1. Validate Table references
    for table_node in ast.find_all(exp.Table):
        t_name = table_node.name.lower()
        if not t_name:
            continue

        # If it's a CTE alias, it's valid within scope
        if t_name in cte_names:
            continue

        if t_name not in visible_tables:
            raise IdentifierPolicyError(f"Table '{table_node.name}' is not in visible schema catalog")

        referenced_identifiers.add(t_name)

    # 2. Expand star projections if present
    for select in ast.find_all(exp.Select):
        new_expressions = []
        for expr in select.expressions:
            if isinstance(expr, exp.Star):
                # Expand star to visible columns from from/join tables
                expanded = False
                for t_node in select.find_all(exp.Table):
                    t_name = t_node.name.lower()
                    if t_name in visible_tables:
                        cols = sorted(visible_tables[t_name])
                        for col in cols:
                            new_expressions.append(exp.Column(this=exp.to_identifier(col), table=exp.to_identifier(t_name)))
                        expanded = True
                if not expanded:
                    # If count(*), keep it
                    new_expressions.append(expr)
            else:
                new_expressions.append(expr)
        select.set("expressions", new_expressions)

    # 3. Validate Column references (excluding star)
    for col_node in ast.find_all(exp.Column):
        c_name = col_node.name.lower()
        t_name = col_node.table.lower() if col_node.table else None

        if not c_name or c_name == "*":
            continue

        if t_name:
            if t_name in cte_names:
                continue
            if t_name not in visible_tables:
                raise IdentifierPolicyError(f"Table '{col_node.table}' referenced in column '{col_node.sql()}' is unauthorized")
            if c_name not in visible_tables[t_name]:
                raise IdentifierPolicyError(f"Column '{c_name}' on table '{t_name}' is not in visible schema catalog")
        else:
            # Unqualified column: must belong to at least one visible table
            found = False
            for t, cols in visible_tables.items():
                if c_name in cols:
                    found = True
                    break
            # Also could be CTE column or alias
            if not found and not cte_names:
                raise IdentifierPolicyError(f"Unqualified column '{c_name}' not found in authorized catalog")

        referenced_identifiers.add(c_name)

    return sorted(list(referenced_identifiers))
