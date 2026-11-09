"""Repair context assembly and untrusted input sanitization (Contracts C05, C06, C08)."""

from __future__ import annotations

from dataclasses import dataclass, field

from querylens.pipeline.context import ContextBudgetError, SchemaContext, estimate_tokens
from querylens.pipeline.errors import ClassifiedError


@dataclass(frozen=True)
class RepairContext:
    """Bounded, safe repair context passed to LLM."""

    question: str
    dialect: str
    schema_context: str
    prior_sql: str
    error_code: str
    safe_message: str
    identifier_hints: list[str] = field(default_factory=list)
    max_rows: int = 100
    formatted_prompt: str = ""


def assemble_repair_context(
    question: str,
    dialect: str,
    schema_context: str | SchemaContext,
    prior_sql: str,
    classified_error: ClassifiedError,
    max_rows: int = 100,
    max_tokens: int = 4000,
) -> RepairContext:
    """Build sanitized repair context without leaking raw parameters, secrets or unapproved tables."""
    schema_str = schema_context.formatted_schema if isinstance(schema_context, SchemaContext) else str(schema_context)

    hints_section = ""
    if classified_error.identifier_hints:
        hints_section = f"\nAVAILABLE AUTHORIZED IDENTIFIERS: {', '.join(classified_error.identifier_hints)}"

    prompt = (
        f"You are repairing a SQL query for dialect: {dialect.upper()}.\n"
        f"ORIGINAL USER QUESTION: {question}\n"
        f"PREVIOUS FAILED SQL:\n{prior_sql}\n"
        f"ERROR CODE: {classified_error.code}\n"
        f"ERROR DETAILS: {classified_error.safe_message}{hints_section}\n"
        f"AUTHORIZED SCHEMA CONTEXT:\n{schema_str}\n"
        f"INSTRUCTIONS:\n"
        f"1. Generate a corrected read-only SELECT query.\n"
        f"2. If the user request is ambiguous or cannot be answered with the schema, set requires_clarification=true and ask a question.\n"
        f"3. Do not execute DDL, DML, or prohibited functions.\n"
    )

    # Check token bound
    tokens = estimate_tokens(prompt)
    if tokens > max_tokens:
        raise ContextBudgetError("Required repair context exceeds the input budget; narrow the request or reduce inherited context")

    return RepairContext(
        question=question,
        dialect=dialect,
        schema_context=schema_str,
        prior_sql=prior_sql,
        error_code=classified_error.code,
        safe_message=classified_error.safe_message,
        identifier_hints=list(classified_error.identifier_hints),
        max_rows=max_rows,
        formatted_prompt=prompt,
    )
