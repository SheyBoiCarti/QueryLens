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
    for sub in ast.find_all(exp.Subquery):
        if sub.alias:
            cte_names.add(sub.alias.lower())

    # Track column aliases defined in query projections
    select_aliases: set[str] = {
        a.alias.lower() for a in ast.find_all(exp.Alias) if a.alias
    }

    referenced_identifiers: set[str] = set()
    table_aliases: dict[str, str] = {}

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
        table_aliases[t_name] = t_name
        if table_node.alias:
            table_aliases[table_node.alias.lower()] = t_name

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
            # Map alias to physical table name
            phys_table = table_aliases.get(t_name, t_name)
            if phys_table in cte_names:
                continue
            if phys_table not in visible_tables:
                raise IdentifierPolicyError(f"Table '{col_node.table}' referenced in column '{col_node.sql()}' is unauthorized")
            if c_name not in visible_tables[phys_table]:
                raise IdentifierPolicyError(f"Column '{c_name}' on table '{phys_table}' is not in visible schema catalog")
        else:
            # Unqualified column: can be projection alias, CTE column, or belong to a visible table
            if c_name in select_aliases or cte_names:
                found = True
            else:
                found = any(c_name in cols for cols in visible_tables.values())

            if not found:
                raise IdentifierPolicyError(f"Unqualified column '{c_name}' not found in authorized catalog")

        referenced_identifiers.add(c_name)

    return sorted(list(referenced_identifiers))
