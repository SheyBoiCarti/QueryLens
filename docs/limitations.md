# QueryLens System Constraints & Limitations

This document describes the operational boundaries, hard limits, and design trade-offs in QueryLens.

## 1. Hard Architectural Limits

| Boundary | Limit | Enforcement Mechanism |
| --- | --- | --- |
| Maximum Result Rows | 1,000 rows | AstLimitTransform injection + sentinel row fetch |
| Maximum SQL Payload Size | 32,768 UTF-8 bytes | Pre-acceptance validation & worker check |
| Follow-Up History Length | <= 5 recent turns | Lineage traversal truncation (latest 5 + root) |
| Follow-Up Prompt Budget | 2,000 tokens | Token estimation check; returns 409 if exceeded |
| Maximum Plottable Data Points | 50 points | Frontend plot eligibility rules; falls back to table |
| Query Execution Timeout | 30.0 seconds | Worker socket deadline & DBAPI cancellation |
| Overall Pipeline Timeout | 60.0 seconds | Budget deadline tracker |

## 2. Follow-Up Query Lineage & Context Drift

- **Lineage Depth:** Traversal walks up to 10 parent ancestors, retaining the latest 5 turns plus initial intent.
- **Context Drift Detection:** If the database catalog snapshot or semantic metrics change between turns, follow-up queries fail with HTTP 409 `FOLLOWUP_CONTEXT_STALE`. Users are offered an explicit action: "Ask as a standalone question" to query without stale assumptions.
- **Context Oversize:** If the inherited context plus schema exceeds 2,000 tokens, the request fails with HTTP 409 `FOLLOWUP_CONTEXT_OVERSIZED`.
- **Private Lineage:** All ancestors in a follow-up chain must be owned by the same user on the same connection. Foreign or deleted parents terminate lineage traversal.

## 3. Data Presentation & Chart Eligibility

- **Chart Types:** QueryLens supports `table`, `single_value`, `line`, and `bar` visualizations.
- **Plot Value Restrictions:**
  - Plottable data must contain between 1 and 50 rows.
  - Plotted numerical values must fall within the JavaScript safe integer range (`Number.MIN_SAFE_INTEGER` to `Number.MAX_SAFE_INTEGER`).
  - Plotted values cannot contain duplicate category keys or inconsistent units.
- **Unsupported-Filter Fallback:** Any query result not meeting strict plot eligibility automatically falls back to an accessible, responsive data table.
- **Volatile Result Caching:** Query results are cached temporarily with an expiry timestamp (`results_expires_at`). Upon expiry, raw result rows are purged from memory, and visualization tabs revert to an expired status banner with a one-click rerun option. Query metadata, SQL, and context lineage are durably retained.

## 4. Date & Time Semantics

- **UTC Boundary Guarantees:** Date filter presets (`this_month`, `this_year`, `fixed`) resolve to UTC execution-time boundaries.
- **Inclusive Ends:** Date range filters treat the end date as inclusive of that full calendar day (through 23:59:59.999 UTC), preventing partial-day cutoff bugs.
- **Clock Dependency:** Date range resolution depends on the server system clock in UTC.

## 5. Saved filter eligibility and review

Only server-discovered, unambiguous root `SELECT` predicates can become filters.
Table aliases resolve to exact physical namespace/table/column identities.
Unsupported predicates, including `OR`, nested scopes, ambiguous columns, and
unsupported date comparisons, remain literal SQL. Date ranges require an
existing `>=` lower bound and `<` upper bound with calendar-date literals. The
compiler preserves defaults and uses `>= start AND < next_day_after_inclusive_end`
for both DATE and timestamp columns; no fractional-second approximation is used.
`LIMIT 0` remains a zero-row query and has no result-count filter.

Saved runs require an exact revision and reject unknown names, invalid scalar
types, choices, and defaults before accepting work. Physical type or namespace
changes require review. Review the stored SQL, run an edited query successfully,
and explicitly replace the saved definition from that completed run. Ordinary
runs and variations leave the stored revision unchanged.

Completion retains typed bindings, supplied selections, resolved date bounds,
and effective row limits. Editable/resavable SQL is reconstructed from AST
nodes; executable statements continue to bind values through the driver. Chart
preferences belong to the accepted revision and apply only to eligible results.
Required inherited schema and repair context are never truncated to fit a budget.
