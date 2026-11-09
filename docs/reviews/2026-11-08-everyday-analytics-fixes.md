# Everyday Analytics review corrections

This records corrections to all 18 findings in
[the original review](2026-11-08-everyday-analytics-review.md). The original
review remains a historical record of its reviewed revision.

## Finding-by-finding evidence

| Finding | Correction | Regression evidence |
| --- | --- | --- |
| 1. Driver compilation | Parse placeholders as AST nodes; escape data percent signs before installing generated driver markers. Literal text cannot become a parameter. | `test_parameter_execution.py` exercises real driver rendering; `test_source_analytics_gate.py` executes literal placeholder text and injection-like bound values through metadata probes and guarded results on both engines. |
| 2. Filter targets | Rediscover at save, update and compilation; compare complete targets and source types. Resolve root aliases to exact physical objects; reject unsupported scopes, self-join occurrences, OR, ambiguity, and forged paths. Boolean slots require boolean AST literals rather than engine-dependent string coercion. | `test_sql_parameters.py` forged/nested/OR and alias cases; `test_saved_questions_api.py::test_save_and_update_verify_server_discovered_targets`. |
| 3. Date boundaries | Expose only existing calendar-date `>=` / `<` pairs. Inclusive UI ends resolve to the following day's exclusive midnight; unsupported source operators retain literal SQL. | Boundary rejection unit cases and real DATE/timestamp source cases include January 31 at 23:59:59 and exclude February 1. |
| 4. Dependencies | Compare exact namespace/table/column spelling and physical `db_type`, in addition to canonical type and metric signatures. | Saved API dependency tests cover `bigint` to `integer` and same-named tables in another namespace. |
| 5. Admission | Require the revision; validate names, scalar types, choices and resolved defaults before reserving work. Repeat compilation in the worker so presets use execution time. | Invalid saved-parameter HTTP tests assert 422 and no new run records. |
| 6. Audit/edit/resave | Persist structured selections, typed bindings, date resolutions and effective row limits in completion. Reconstruct editable/resavable SQL with AST literals, keeping execution parameterized. | Source journeys request 200 rows, change selections, resave the completed filtered run and execute the new definition against actual source data. |
| 7. Limits | Clamp configured defaults independently of exposed slots. Preserve author `LIMIT 0` and omit its result-count selector. | No-filter lowered-budget and zero-limit unit cases. |
| 8. Context | Prioritize inherited tables, reject missing required schema, omit optional labels/examples when necessary, and reject oversized repair prompts without truncation. Admission preflights follow-up schema; worker errors remain actionable. | Follow-up integration tests inspect full required schema and reject oversized schema/repair prompts; semantic tests assert complete metric DSL within byte budgets. |
| 9. Retained expiry | Schedule expiry across every retained answer and check timestamps before rendering. Clear rows and presentation even while another answer is polled. | Workspace test returns to an expired retained answer with revalidation deliberately pending and asserts protected rows/explanation are absent. |
| 10. Rerun origin | Dispatch saved runs with revision/selections, follow-ups with parent lineage, and manual runs with SQL/source/effective limits. | HTTP-backed workspace rerun tests assert each endpoint and payload. |
| 11. Draft recovery | Supply retained SQL drafts back to remounted editors. Retain follow-up text after rejected submissions or execution failures; handle rejection without an unhandled promise. | Workspace manual-failure test returns to the source editor and asserts the submitted draft; follow-up workflow and full frontend suites pass. |
| 12. Integer controls | Render numeric/boolean categories by source type, retaining scalar types and rejecting fractional integer entry. | Typed category regression asserts numeric `2`, rejects `2.5`; saved execution validates types independently. |
| 13. Authoring/review | Shared typed definition editor supports slot selection, labels, defaults and category options. Manager edits definitions, reviews/edits SQL into a new manual run, explicitly replaces from a completed run with revision checking, and accepts a variation request without updating stored SQL. | HTTP-backed authoring tests inspect save/edit/review/replacement payloads and variation behavior. Backend replacement validates the new template and rediscovers its slots. |
| 14. Search/paging | Send `search` and append cursor pages. | Saved manager HTTP test asserts search and cursor requests and access to the next page. |
| 15. Stale requests | Abort list/detail requests; guard responses by controller, selection and current connection. Hide detail/list entries from other connections during transitions. | Delayed previous-connection HTTP response cannot replace the current list. |
| 16. Temporal charts | Position temporal points using elapsed timestamps while keeping exact accessible labels and table order. | SVG regression verifies January 2 lies 1/364 of the January 1–December 31 distance. |
| 17. Chart preference | Derive presentation from the accepted saved revision's preference, applying it only to eligible data. | HTTP test changes the saved preference after completion and confirms the historical run still uses its accepted table preference; unit tests retain table fallback for unsafe values. |
| 18. Acceptance gates | Isolated real-source fixtures replace ambient Aiven credentials; required mode fails missing engines. CI provisions PostgreSQL 17/18 and Oracle MySQL 8.0/8.4. PowerShell checks schema/backend/frontend separately and runs required source journeys. SQLite test metadata uses separate connections to eliminate shared-connection transaction races. | Full backend, frontend, source-version, migration, contract and release checks below. Missing-fixture negative gate fails as intended. |

## Verification

All checks use the current worktree. Source journeys use real adapters and
`SafeExecutor`, HTTP admission/polling, source metadata probes and guarded
results. They assert actual rows, parameterized literal preservation, date and
timestamp boundaries, filtered resaving, and DML rejection with unchanged
source data. Source-driver assertions do not use canned executor results.

- Full backend: `QUERYLENS_REQUIRE_SOURCES=1 .venv/bin/pytest apps/api/tests -q --tb=short` with disposable PostgreSQL 16 and Oracle MySQL 8.4 configured: **329 passed**, zero skips.
- Full frontend: `npm run test --workspace=apps/web`: **95 passed**, including the final connection-response guards and draft/expiry regressions.
- PostgreSQL **17.0** with Oracle MySQL **8.0.36**: source/adapter/executor/reflection/natural-language journeys plus disposable migration roundtrips: **28 passed**.
- PostgreSQL **18.0** with Oracle MySQL **8.4.0**: the same source and migration gate: **28 passed**.
- After the final predicate guards, the real DATE/timestamp HTTP source journeys were rerun on both version pairs: **4 passed per pair**.
- Required MySQL fixture deliberately absent: source gate exits **1**, with fixture errors rather than skips.
- Full release script: `pwsh -NoProfile -File scripts/verify.ps1` with required source fixtures: **exit 0**, every phase and source gate passed.
- Ruff, Mypy, OpenAPI `--check`, frontend lint/typecheck, production build, and `git diff --check`: passed.

Local PostgreSQL 17/18 binaries were built in temporary directories from their
release sources. Oracle MySQL binaries and data also live in temporary
directories. No production or external source data was used. CI uses versioned
service containers; see [development instructions](../development.md#everyday-analytics-source-gates)
for reproducing the required fixture gate.
