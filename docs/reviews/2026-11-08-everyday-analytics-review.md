# Everyday Analytics branch review

## Overall verdict: Needs Fixes

- **Reviewed branch:** `feat/everyday-analytics-persistence`
- **Reviewed HEAD:** `f664a6c2f9b4489d4a359a74af5914dd9d8da477`
- **Merge base with `main`:** `ef51c967f7a9ba5ec29dbc9be265419e691a5982`
- **Requirements:** [2026-11-08-everyday-analytics.md](../superpowers/plans/2026-11-08-everyday-analytics.md)
- **Scope:** All branch changes against the merge base, including all 13 implementation tasks.
- **Review date:** 2026-11-08

The branch contains a SQL binding policy bypass, incorrect filter behavior, and incomplete workspace workflows. P1 findings should block merging.

This records the read-only review of the revision above. No fixes or commits were made during the review. This document was subsequently added at the user's request. File references and line numbers refer to the reviewed revision.

Corrections and verification evidence are tracked in [the follow-up](2026-11-08-everyday-analytics-fixes.md). The findings below describe the original reviewed revision.

## Findings ranked by severity

### 1. P1 — Driver compilation can turn literal text into executable SQL

**Reference:** [sql/bindings.py:35](../../apps/api/src/querylens/sql/bindings.py#L35)

The compiler replaces placeholder-looking text inside quoted literals. With a valid parameterized query, PyMySQL rendered a metadata probe beginning `SELECT '' OR SLEEP(30) -- …`, introducing a function absent from the validated AST. This was reproduced through driver rendering, not execution against a live MySQL server. A disposable PostgreSQL roundtrip also changed literal `%(p)s` into `$1` and `%%` into `%`.

**Recommended correction:** Generate driver placeholders from AST nodes and escape literal percent signs separately. Add real-driver tests for placeholder-looking literals as well as bound values, through metadata probes and guarded result queries.

### 2. P1 — Saved filters are not restricted to server-discovered predicates

**References:** [api/saved_questions.py:102](../../apps/api/src/querylens/api/saved_questions.py#L102), [sql/parameters.py:470](../../apps/api/src/querylens/sql/parameters.py#L470)

Save requests store client definitions directly. Compilation replaces the first equality matching a column name, ignoring scope, table, namespace, and predicate path. An authenticated reproduction saved and executed a forged filter inside an unsupported `OR`. Ordinary aliased queries also lose eligible slots because discovery treats table aliases as physical table names.

**Recommended correction:** Rediscover and verify exact targets at save, update, and execution. Resolve aliases and physical objects through SQL scopes, enforce unique supported predicates, and reject forged or ambiguous definitions.

### 3. P1 — Date filters include incorrect boundaries

**Reference:** [sql/parameters.py:501](../../apps/api/src/querylens/sql/parameters.py#L501)

Compilation replaces values without changing comparison operators. An inclusive January 31 selection becomes `<= February 1`, including an extra day for DATE columns. Existing `>` starts also remain exclusive.

**Recommended correction:** Compile explicitly to `>= start AND < end_exclusive`, or reject unsupported source predicates. Verify both DATE and timestamp behavior, including the default selection.

### 4. P2 — Saved dependency checks miss physical type and namespace changes

**Reference:** [semantics/saved_questions.py:34](../../apps/api/src/querylens/semantics/saved_questions.py#L34)

Dependency validation indexes tables by lowercased name and compares only canonical column types. A stored `bigint` reference was accepted against `integer`. Namespace collisions and physical type changes therefore do not receive the required dependency comparison.

**Recommended correction:** Compare exact namespace/table/column identities and physical `db_type` signatures before accepting a rerun. Preserve engine-sensitive identifier spelling.

### 5. P2 — Invalid run parameters are accepted instead of rejected synchronously

**References:** [api/saved_questions.py:319](../../apps/api/src/querylens/api/saved_questions.py#L319), [api/query_schemas.py:105](../../apps/api/src/querylens/api/query_schemas.py#L105)

The run endpoint admits work without validating values. Wrong types returned `202`, then failed with `UNKNOWN_ERROR`; unknown parameter names were silently ignored. The request model also makes `expected_revision` optional despite the required revision contract.

**Recommended correction:** Require the revision and validate names, types, choices, and defaults before admission. Preserve worker revalidation and execution-time resolution of date presets.

### 6. P2 — Parameterized run metadata cannot support reliable audit, editing, or resaving

**References:** [pipeline/direct.py:147](../../apps/api/src/querylens/pipeline/direct.py#L147), [pipeline/lifecycle.py:84](../../apps/api/src/querylens/pipeline/lifecycle.py#L84)

Context is built from a placeholder template, while publication discards structured resolved parameters. Resaving a completed filtered run produced a definition whose rerun was rejected for unresolved placeholders. A 200-row request also remained recorded as 100 in history and parameter discovery. Applied-filter text does not retain the complete structured supplied selection and resolution contract.

**Recommended correction:** Persist supplied selections, typed resolutions, and effective limits with completion. Use retained binding metadata to reconstruct reusable and editable SQL through ASTs, without textual value substitution.

### 7. P2 — Saved row-limit edge cases fail legitimate operations

**Reference:** [sql/parameters.py:321](../../apps/api/src/querylens/sql/parameters.py#L321)

Configured limits are clamped only when a result-count parameter exists. A definition without filters fails after the configured maximum is lowered instead of using the bounded default. Discovery also raises a validation error for valid `LIMIT 0` queries because it constructs a result-count default of zero.

**Recommended correction:** Apply effective row limits independently of exposed filters and preserve zero-limit queries without constructing invalid parameter definitions.

### 8. P2 — Follow-up budgeting silently drops essential context

**References:** [pipeline/context.py:129](../../apps/api/src/querylens/pipeline/context.py#L129), [pipeline/orchestrator.py:195](../../apps/api/src/querylens/pipeline/orchestrator.py#L195), [pipeline/repair_context.py:55](../../apps/api/src/querylens/pipeline/repair_context.py#L55)

Schema assembly verifies that metric tables fit, but not inherited tables. A reproduction omitted the required parent table while continuing with unrelated schema. The repair path also permits byte truncation that removed all inherited context.

**Recommended correction:** Reserve essential inherited context and schema before optional content. Reject oversized requests with an actionable error instead of truncating required context, including during repair.

### 9. P2 — Retained answers outlive their result expiry

**Reference:** [WorkspaceView.tsx:229](../../apps/web/src/features/workspace/WorkspaceView.tsx#L229)

Changing the polling target cancels the previous answer's expiry timer, but its rows remain in `loadedRuns`. Returning to that answer displayed expired protected rows before revalidation completed.

**Recommended correction:** Enforce expiry across every retained run. Clear rows and presentation before rendering expired entries, independently of which run is currently polled.

### 10. P2 — Expired reruns use the wrong execution origin

**Reference:** [WorkspaceView.tsx:501](../../apps/web/src/features/workspace/WorkspaceView.tsx#L501)

Saved questions and follow-ups are sent to the natural-language endpoint using only question text. This loses saved filters/revision or follow-up parent context and invokes generation. The behavior was reproduced by inspecting the actual frontend request.

**Recommended correction:** Route reruns through the corresponding origin with its retained parameters, revision, limits, and lineage.

### 11. P2 — Failure recovery loses user drafts

**References:** [SQLPanel.tsx:29](../../apps/web/src/features/workspace/SQLPanel.tsx#L29), [FollowUpBar.tsx:26](../../apps/web/src/features/workspace/FollowUpBar.tsx#L26)

SQL drafts reset on remount; workspace draft storage is never supplied back to the editor. A failed manual run followed by returning to its source lost the submitted draft. Follow-up input also clears after rejected submissions because the workspace catches errors and resolves normally.

**Recommended correction:** Restore controlled drafts across selection and navigation. Clear follow-up input only after acceptance, and preserve it after submission or execution failures.

### 12. P2 — Integer category controls send strings

**Reference:** [SavedQuestionFilters.tsx:191](../../apps/web/src/features/workspace/SavedQuestionFilters.tsx#L191)

The category control uses a text input whenever choices are absent, which is the normal discovery result. Editing integer `1` to `2` emitted string `"2"`, which the backend rejects.

**Recommended correction:** Render controls according to `source_type` and preserve scalar types. Validate numeric entry without silently rounding values.

### 13. P2 — Required saved-question authoring and review flows are missing

**References:** [SavedQuestionsModal.tsx:170](../../apps/web/src/features/workspace/SavedQuestionsModal.tsx#L170), [SavedQuestionsManager.tsx:78](../../apps/web/src/features/workspace/SavedQuestionsManager.tsx#L78)

The save modal offers labels only: no slot deselection, defaults, or category-option authoring. The manager lacks definition editing, successful-run replacement, and review/variation actions. These Task 11 requirements are not implemented by the existing controls.

**Recommended correction:** Implement the required authoring and explicit revision/review flows, with HTTP-backed tests that assert their payloads and resulting behavior.

### 14. P2 — Saved-question search and pagination are incomplete

**Reference:** [SavedQuestionsManager.tsx:36](../../apps/web/src/features/workspace/SavedQuestionsManager.tsx#L36)

The manager sends `query=`, while the API accepts `search=`. It also ignores `next_cursor`, leaving questions beyond the first page inaccessible.

**Recommended correction:** Use the documented search parameter and implement cursor pagination.

### 15. P2 — Saved-manager requests can restore another connection's state

**Reference:** [SavedQuestionsManager.tsx:48](../../apps/web/src/features/workspace/SavedQuestionsManager.tsx#L48)

Connection changes reset selection without aborting or guarding outstanding requests. A delayed connection A response replaced connection B's list after switching. Detail requests have the same missing stale-response protection.

**Recommended correction:** Abort outstanding requests and guard list/detail responses against the current connection and selection.

### 16. P2 — Temporal charts use row index instead of elapsed time

**Reference:** [AccessibleChart.tsx:48](../../apps/web/src/features/workspace/charts/AccessibleChart.tsx#L48)

Line charts space points equally by row index. January 1, January 2, and December 31 appeared at equally spaced coordinates, distorting the trend.

**Recommended correction:** Scale temporal line-chart positions using timestamps while retaining exact accessible labels and unchanged table ordering.

### 17. P2 — Saved chart preferences are ignored

**Reference:** [api/queries.py:244](../../apps/api/src/querylens/api/queries.py#L244)

Preferences are persisted, but presentation is derived without consulting them. A saved table preference cannot affect the displayed result.

**Recommended correction:** Carry the accepted revision's preference into presentation and apply it only when compatible with the result shape.

### 18. P2 — Required acceptance gates are incomplete and can conceal failures

**References:** [test_parameter_execution.py:26](../../apps/api/tests/integration/test_parameter_execution.py#L26), [ci.yml:13](../../.github/workflows/ci.yml#L13), [verify.ps1:128](../../scripts/verify.ps1#L128)

The parameter execution tests check strings and mappings without executing parameterized source queries. CI does not provision the required source-engine journeys. The verification script also runs three native commands in one step and checks only the final exit code, potentially masking schema or backend-test failures.

**Recommended correction:** Add real PostgreSQL and Oracle MySQL manual/parameterized execution gates, fail when required fixtures are missing, and check each verification command independently. Do not substitute canned executor results for source-driver assertions.

## Completion status of all 13 tasks

| Task | Completion status |
| --- | --- |
| 1. Persistence, domain context, and repositories | Implemented; disposable PostgreSQL migration roundtrip passed. |
| 2. Labels, metrics, retrieval, and semantic versions | Implemented; relevant tests passed. |
| 3. Labels and structured metric editor | Implemented; relevant frontend tests passed. |
| 4. Verified context and cache-bound presentation | Partial; parameterized context/audit integration remains incomplete. |
| 5. Shared lifecycle and manual SQL | Implemented; full source-engine acceptance remains unverified. |
| 6. Slots, immutable tokens, and driver bindings | Incomplete; findings 1–3 and 7. |
| 7. Saved definitions and direct reruns | Incomplete; findings 4–7. |
| 8. Follow-up lineage and budgets | Incomplete; finding 8. |
| 9. Accessible presentation and expiry | Incomplete; findings 9, 16, and 17. |
| 10. Workspace state and SQL editing | Partial; draft recovery is broken. |
| 11. Saved-question UI and typed filters | Incomplete; findings 10 and 12–15. |
| 12. Branching and failure recovery | Partial; branching exists, but failed drafts are lost. |
| 13. Contracts and acceptance gates | Incomplete; red checks and missing engine coverage. |

## Verification results

Commands ran from the repository root using the existing `.venv` and installed npm dependencies. Additional reproductions used authenticated test fixtures, in-memory metadata, disposable PostgreSQL, PyMySQL statement rendering, and frontend components loaded through Vite/JSDOM. No reproduction code was added to the repository.

| Check | Command or method | Result |
| --- | --- | --- |
| Full backend suite | `.venv/bin/python -m pytest apps/api/tests -q` | **301 passed, 5 failed** |
| Changed backend test files | Selected changed `test_*.py` files from `git diff --name-only main...HEAD`, then ran pytest with `-q --tb=short` | **173 passed, 1 intermittent failure** |
| Manual SQL suite rerun | `.venv/bin/python -m pytest apps/api/tests/integration/test_manual_sql_execution.py -q --tb=short` | **14 passed** |
| Frontend tests | `npm run test --workspace=apps/web` | **85 passed** |
| Backend lint | `.venv/bin/ruff check apps/api` | Passed |
| Backend type check | `.venv/bin/mypy --config-file apps/api/mypy.ini apps/api/src` | Passed |
| OpenAPI parity | `.venv/bin/python scripts/export_schema.py --check` | Passed |
| Frontend type check | `npm run typecheck --workspace=apps/web` | Passed |
| Frontend production build | `npm run build --workspace=apps/web` | Passed |
| Frontend lint | `npm run lint --workspace=apps/web` | **Failed: 9 errors in changed files** |
| Disposable PostgreSQL migrations | Migration tests included in the backend suites | Passed on **PostgreSQL 16.15** |
| Disposable PostgreSQL binding reproduction | Actual psycopg roundtrip through `compile_driver_statement` | Reproduced literal corruption in finding 1 |

### Backend failures and unresolved verification issues

The full backend suite failed these tests:

- `tests/integration/test_adapters.py::test_live_aiven_database_connections`
- `tests/integration/test_execution.py::test_live_execution_on_postgresql`
- `tests/integration/test_execution.py::test_live_execution_on_mysql`
- `tests/integration/test_schema_reflection.py::test_live_table_discovery`
- `tests/integration/test_vertical_slice.py::test_full_vertical_slice_workflow`

Live-source failures included TLS certificate verification errors. The vertical-slice test returned `429` in the full run and failed after acceptance when run alone; its cause remains unresolved. These failures are not asserted to be newly introduced branch regressions without further isolation.

The focused changed-file run intermittently failed `test_manual_completes_without_provider_and_retains_author_limit[-None]` with an empty attempt list. The manual SQL suite subsequently passed all 14 tests in isolation. The intermittent failure remains a verification issue, not a proven production failure.

Frontend lint reported `@typescript-eslint/no-explicit-any` errors in:

- `apps/web/src/api/client.ts:68`
- `apps/web/src/features/workspace/SavedQuestionFilters.tsx:72,73,91,95,106,110`
- `apps/web/src/features/workspace/charts/AccessibleChart.tsx:8`
- `apps/web/src/features/workspace/charts/plotValues.ts:38`

PostgreSQL 17/18 and Oracle MySQL 8.0/8.4 compatibility remain unverified. The disposable PostgreSQL migration and binding reproductions do not establish complete manual and parameterized source-execution compatibility. Passing mocked execution tests does not establish the required source-driver behavior.
