"""AST limit bounding and offset clamping (Contracts C06, C07)."""

from __future__ import annotations

from sqlglot import exp

MAX_ALLOWED_OFFSET = 10000


class LimitPolicyError(Exception):
    """Raised when query uses invalid or excessive limits/offsets."""
    pass


def bound_query_limits(ast: exp.Expression, max_rows: int = 100) -> tuple[exp.Expression, int]:
    """Inject or clamp top-level literal LIMIT to min(original, max_rows + 1).
    
    Returns:
        (transformed_ast, effective_limit)
    """
    if max_rows < 1 or max_rows > 1000:
        raise LimitPolicyError(f"max_rows must be between 1 and 1000, got {max_rows}")

    target_fetch_limit = max_rows + 1

    # Check top-level limit
    limit_node = ast.args.get("limit")
    if limit_node is not None:
        this_limit = limit_node.expression
        if not isinstance(this_limit, exp.Literal) or not this_limit.is_int:
            raise LimitPolicyError("Only literal integer LIMIT clauses are permitted")

        original_limit = int(this_limit.this)
        if original_limit < 0:
            raise LimitPolicyError("Negative LIMIT is not allowed")

        # Clamp to min(original, max_rows + 1)
        clamped = min(original_limit, target_fetch_limit)
        limit_node.set("expression", exp.Literal.number(clamped))
        effective_limit = clamped
    else:
        # Inject LIMIT clause
        ast.set("limit", exp.Limit(expression=exp.Literal.number(target_fetch_limit)))
        effective_limit = target_fetch_limit

    # Check offset
    offset_node = ast.args.get("offset")
    if offset_node is not None:
        this_offset = offset_node.expression
        if not isinstance(this_offset, exp.Literal) or not this_offset.is_int:
            raise LimitPolicyError("Only literal integer OFFSET clauses are permitted")
        offset_val = int(this_offset.this)
        if offset_val > MAX_ALLOWED_OFFSET:
            raise LimitPolicyError(f"OFFSET {offset_val} exceeds maximum allowed of {MAX_ALLOWED_OFFSET}")

    return ast, effective_limit
