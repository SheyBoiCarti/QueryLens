"""Authorize physical relations before scoped SQLGlot column resolution."""

from __future__ import annotations

from sqlglot import exp
from sqlglot.errors import OptimizeError, SchemaError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope
from sqlglot.schema import MappingSchema

from querylens.domain.schema import CatalogSnapshot


class IdentifierPolicyError(Exception):
    """An identifier cannot be resolved exclusively from the authorized catalog."""


def resolve_identifiers(ast: exp.Expression, snapshot: CatalogSnapshot) -> list[str]:
    """Validate physical namespaces, then resolve aliases, CTEs and stars per scope.

    Missing tables/columns are never inferred from SQL or the remote database.
    Unqualified relations must identify exactly one authorized physical table.
    """
    dialect = "postgres" if snapshot.engine == "postgresql" else snapshot.engine
    normalize_identifiers(ast, dialect=dialect)
    visible = {(t.namespace, t.name): t for t in snapshot.tables}
    schema = MappingSchema(dialect=dialect, normalize=False)
    for table in snapshot.tables:
        schema.add_table(
            exp.Table(
                this=exp.to_identifier(table.name, quoted=True), db=exp.to_identifier(table.namespace, quoted=True)
            ),
            {column.name: column.db_type for column in table.columns},
            normalize=False,
        )

    permitted: set[str] = set()
    try:
        for scope in traverse_scope(ast):
            for _, source in scope.selected_sources.values():
                if not isinstance(source, exp.Table):
                    continue  # Derived/CTE scopes are validated independently.
                alias = source.args.get("alias")
                if isinstance(alias, exp.TableAlias) and alias.columns:
                    # The catalog contains visible columns, not complete physical
                    # ordinals. Positional renaming could expose hidden columns.
                    raise IdentifierPolicyError("Physical table column alias lists are prohibited")
                if not isinstance(source.this, exp.Identifier) or source.catalog:
                    raise IdentifierPolicyError("Catalog-qualified and dynamic table sources are prohibited")
                candidates = [
                    table
                    for (namespace, name), table in visible.items()
                    if name == source.name and (not source.db or namespace == source.db)
                ]
                if len(candidates) != 1:
                    raise IdentifierPolicyError(f"Table '{source.sql()}' is not uniquely authorized")
                table = candidates[0]
                if not table.columns:
                    raise IdentifierPolicyError(f"Table '{table.name}' has no authorized columns")
                source.set("db", exp.to_identifier(table.namespace, quoted=True))
                permitted.add(f"{table.namespace}.{table.name}")

        for column in ast.find_all(exp.Column):
            if column.catalog or (column.db and (column.db, column.table) not in visible):
                raise IdentifierPolicyError("Column namespace is not in the authorized catalog")
        qualify(
            ast,
            dialect=dialect,
            schema=schema,
            expand_stars=True,
            allow_partial_qualification=False,
            validate_qualify_columns=True,
            quote_identifiers=True,
        )
        for select in ast.find_all(exp.Select):
            if any(projection.is_star for projection in select.expressions):
                raise IdentifierPolicyError("Projection star could not be expanded from authorized columns")
        if ast.find(exp.TableColumn):
            raise IdentifierPolicyError("Whole-row composite references are prohibited; select authorized columns")
        for column in ast.find_all(exp.Column):
            if not column.is_star:
                permitted.add(column.sql(dialect=dialect))
    except (OptimizeError, SchemaError) as exc:
        raise IdentifierPolicyError(f"Identifier resolution failed: {exc}") from exc
    return sorted(permitted)
