# Everyday Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. Follow the user's chosen execution method; this document does not authorize implementation or delegation by itself.

**Goal:** Deliver trustworthy answer presentation, editable read-only SQL, saved questions with typed filters, business labels and metric synonyms, and bounded follow-ups within QueryLens's existing security and execution architecture.

**Architecture:** Extend the FastAPI/React modular monolith. Reuse one admission/cancellation/completion lifecycle for all execution origins, add immutable driver bindings to the validated-query contract, persist versioned server-owned query context, and derive result-dependent presentation only from currently authorized cached rows. Track semantic versions separately from physical catalog hashes and compare referenced dependencies explicitly.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy Core, Alembic, Pydantic v2, sqlglot, psycopg, PyMySQL, React 18, TypeScript 5, Tailwind, Vitest, pytest. No chart library or SQL editor dependency is required.

**Spec:** [Everyday Analytics design](../specs/2026-11-07-everyday-analytics-design.md).

**Revision:** Updated after the codebase review on 2026-11-08. This replaces the original implementation instructions and test examples. No feature implementation or test execution is claimed.

## Global Constraints

- Supported sources remain PostgreSQL 16/17/18 and Oracle MySQL 8.0/8.4, subject to existing tested-version rules. Production metadata remains PostgreSQL; SQLite remains useful for isolated repository tests.
- Resources remain private to the connection owner. Unknown and foreign IDs produce the same 404. Every mutation retains authentication, approved-origin, and session-bound CSRF checks.
- Every origin preserves visible-catalog validation, function restrictions, read-only execution, configured budgets, cancellation, current delivery authorization, and terminal-state guards. Manual/saved execution never calls an LLM, including repair.
- Respect lowered configured limits in every origin: row count, SQL UTF-8 bytes, admission, and total/statement/connect/cleanup deadlines. Hard maxima remain 1,000 rows and 32,768 SQL bytes. Preserve the fetch sentinel and smaller author-written limits.
- Results remain volatile with at most 300-second TTL and existing byte/eviction limits. Never persist source rows or row-derived summaries. Charts and result-derived explanations share row availability and authorization.
- Filters modify only server-discovered supported predicates or result count. Use typed AST slots and DBAPI values, never SQL fragments, text substitution, or arbitrary client-selected AST paths. Unsupported queries can be saved without filters.
- Date ranges use inclusive starts and exclusive ends. An inclusive date-only UI end becomes the following midnight. Resolve this month/year in UTC once at run start and retain exact boundaries. Respect declared DATE versus timestamp types.
- Charts support line, bar, single value, and table fallback, with at most 50 points. No sampling, invented totals/currency, or silent precision loss. Warnings remain visible outside collapsed technical details.
- Follow-ups include at most five authorized ancestors and 2,000 estimated tokens within the existing total prompt budget. The current estimator counts UTF-8 bytes; use it consistently. Never include result rows or silently truncate required context.
- Exclude sharing, clarification wizards, dashboards, scheduling, new engines, general report building, and persisted answer snapshots.
- Synchronize API/TypeScript contracts as endpoints are introduced; Task 13 supplies the final combined gate, not the first contract update.

## Current Codebase: Reuse and Required Extensions

Paths below are relative to apps/api/src/querylens or apps/web/src unless stated otherwise.

| Existing code | Consequence |
| --- | --- |
| sql/policy.py, sql/identifiers.py, sql/functions.py, sql/limits.py | Extend current validation, qualification, function restrictions, and literal limit policy. |
| domain/query.py and execution/executor.py | Factory/executor currently hash SQL alone. Change both together; a frozen dataclass containing a mutable dict is insufficient. |
| execution/postgres.py, execution/mysql.py, execution/bounds.py | Both metadata probes and guarded result queries currently execute without bindings. Extend both statements and both drivers. |
| pipeline/orchestrator.py | Reuse lease activation, total deadlines, source cancellation, cleanup, and publication. _execute_source alone is not a lifecycle. |
| persistence/repositories/query_runs.py | create lacks origin/relationships; update_state cannot store new context and refuses updates after completion. Extend before callers. |
| api/queries.py and api/query_schemas.py | Response dictionaries are built explicitly. Pydantic additions alone do not expose stored fields. |
| domain/schema.py and pipeline/context.py | Physical hashes exclude labels/metrics; metric ranking excludes configured synonyms. Add explicit semantic versions and retrieval integration. |
| api/metrics.py and semantics/metrics.py | Reuse structured DSL/hash; add versioned updates and conflict checks rather than another metric language. |
| jobs/results.py, api/exports.py, api/history.py | Extend current cache-authorized delivery, history, retention, and deletion without persisting results. |
| features/workspace/WorkspaceView.tsx | Current active-run state replaces the displayed answer and polling stops at completion. Separate selection, in-flight run, parent, draft, and expiry. |
| api/client.ts and scripts/export_schema.py | Client lacks PUT. Exporter writes JSON only, not TypeScript. Account for both explicitly. |

Recheck symbols before editing; old line ranges were not reliable implementation boundaries.

## Shared Contracts and Implementation Decisions

These are new interfaces to implement in the named tasks, not existing APIs.

### Run context and versions — Tasks 1, 2, 4

- RunOrigin is natural_language, follow_up, manual_sql, or saved_question.
- Add strict frozen models in domain/analytics.py: ObjectReference(namespace, table_name, column_name, canonical_type, db_type), MetricReference(id, key, version, dsl_hash), LabelReference(namespace, table_name, column_name, display_name, description, version), AppliedFilter(slot_id, column, operator, value), and RunContext.
- RunContext contains effective_question, canonical_sql_template, author_limit, applied_filters, metric_references, label_references, referenced_objects, snapshot_hash, policy_version, and semantic_version. Bound strings/lists and encoded JSON to existing context/request budgets. No rows, row counts, or computed measures.
- Task 1 also declares the frozen BoundParameter and ResolvedParameters data models used by earlier context signatures; Task 6 implements their binding/compilation behavior. ResolvedParameters defaults to empty bindings/values with optional resolved dates and an effective max_rows, so Task 4 never imports a type deferred to Task 6.
- Canonical SQL plus resolved structured filters is authoritative. A follow-up's stored context must be self-contained; its effective question cannot consist only of a fragment such as "Only South Africa." Unknown business meaning receives neutral wording.
- Record signatures of referenced physical objects/types and metric versions/hashes. A monotonic connection semantic_version changes on label/metric mutations; it signals context drift but does not prove a saved definition's referenced metric changed.
- Saved reruns accept unrelated changes after current-policy revalidation. Removed/changed referenced objects/types or changed/removed/disabled referenced metrics require explicit review: SAVED_QUESTION_REVIEW_REQUIRED, HTTP 409. Policy changes require reauthorization/revalidation without expanding exposed slots. Follow-ups reject physical snapshot, policy, or semantic-version drift with FOLLOWUP_CONTEXT_STALE, HTTP 409.
- Historical label copies are metadata filtered against current visibility at delivery. No separate label-history table is required.

### SQL provenance, slots, and binding contract — Tasks 5, 6

- Add validate_query_artifact(sql, connection_id, engine, snapshot, max_rows=100) -> ValidatedArtifact. Return the executable token, authorized canonical template_sql before fetch-limit injection, and original top-level author_limit. Preserve validate_and_bound_sql(...) -> ValidatedQuery as a compatibility wrapper.
- Only authorized AST output becomes a template. Never save an unchecked submitted draft. Original LIMIT 20 remains authoritative; injected LIMIT 101 for max_rows=100 must not become an author cap. Legacy runs with unknown provenance retain their canonical cap until explicit edit/resave.
- ParameterDefinition has slot_id, name, label, param_type, source_type, target, allowed_values, and default_value. ParameterTarget has canonical scope/predicate paths, physical namespace/table/column, and operator; date ranges identify both comparison slots. Verify targets against the canonical template at save/update/run. Names/labels are not AST locators.
- param_type is date_range, category, or result_count. Category values are strict JSON string/int/finite-float/bool scalars with exact type-aware membership and one declared source type. Reject null/arrays/objects. Support at most one category selector initially; never enumerate source values automatically.
- DateRangeInput is a strict discriminated union: {mode:"fixed",start_date:"YYYY-MM-DD",end_date_inclusive:"YYYY-MM-DD"}, {mode:"this_month"}, or {mode:"this_year"}. The server converts those calendar selections to typed inclusive-start/exclusive-end values using the declared source type and UTC rules. Persist both supplied selection and resolved boundaries. Category inputs are the typed scalar itself; result_count is a strict integer. Reject extra union fields and unknown names.
- extract_eligible_parameters(template_sql: str, snapshot: CatalogSnapshot, engine: str, author_limit: int | None) -> list[ParameterDefinition]. Resolve source types and scopes. Offer only unambiguous existing conjunctive WHERE predicates. Reject OR, HAVING, JOIN predicates, correlated/derived ambiguity, and repeated indistinguishable targets. Do not move predicates or infer joins. Result count is server-owned.
- compile_parameterized_query(template_sql: str, definitions: tuple[ParameterDefinition, ...], values: Mapping[str, object], snapshot: CatalogSnapshot, connection_id: str, engine: str, max_rows: int, author_limit: int | None, now: datetime) -> ValidatedArtifact. Verify slots/types, resolve defaults/UTC presets, install named placeholder AST nodes, validate, and mint a token. The artifact also carries ResolvedParameters: supplied values, exact date boundaries, effective row limit, and immutable bindings.
- BoundParameter(name, scalar_type, value) is frozen; token bindings are a copied tuple, with immutable supported driver scalar values, including typed dates/datetimes/Decimal as appropriate. Use one deterministic typed fingerprint function in minting and verification, covering SQL, bindings, connection, engine, policy, snapshot, identifiers, and limits. Existing callers default to empty bindings.
- Parameterized canonical_sql contains sqlglot named placeholder nodes, not driver formatting. The validator permits only exact server-owned placeholder/binding sets. Manual SQL with unresolved placeholders is rejected. Executor checks fingerprint, bindings, current connection/policy/snapshot, and revalidates canonical AST before source dispatch. This remains an internal capability, not protection from malicious Python code.
- compile_driver_statement(sql: str, engine: str, bindings: tuple[BoundParameter, ...]) -> tuple[str, Mapping[str, object]] lives in sql/bindings.py. Render placeholder nodes as psycopg/PyMySQL named parameters without substituting values. Apply after probe/guard transformations and pass bindings to both cursor executions. Correctly escape literal percent signs for the parameter protocol. Never parse DBAPI placeholder text as user SQL or apply the user-function policy to trusted guard-wrapper internals.

### HTTP contracts — owning tasks 2, 5, 7, 8

- Keep the queued response {query_id, status:"queued"}, polling status meanings, and standard error envelope. Synchronous ownership/eligibility/value/drift failures occur before acceptance; SQL policy failures found by workers become terminal rejected runs.
- POST /api/v1/queries/sql: {connection_id, sql, source_query_id?, max_rows}. Optional source must be completed, owner-authorized, and same connection. Retain submitted draft separately from bounded executed SQL.
- GET/PUT /api/v1/connections/{connection_id}/labels: response {semantic_version, labels}; PUT replaces visible labels atomically with expected_semantic_version. Concurrent changes return 409. Hidden records cannot be returned or republished.
- Retain metric routes; add PATCH /api/v1/connections/{connection_id}/metrics/{metric_id}: {expected_version, dsl?, enabled?}. Normalize aliases and reject conflicts among enabled keys, names, and synonyms. Return incremented version.
- GET /api/v1/queries/{query_id}/parameters: {template_fingerprint, definitions}; requires a completed owner run and current catalog authorization. Return candidates without sampling rows.
- Discovery fills the result_count default from the source run's max_rows, never from its injected sentinel. Saved definitions persist default_max_rows even when saved with no filters; reruns use that default bounded by current configuration and author_limit.
- POST /api/v1/saved-questions: {source_query_id, title, description?, parameters, chart_preference?}. Selections reference server-discovered slot IDs; author may supply labels/defaults/category options. SQL, user, connection, provenance, and versions come from the source run.
- GET /api/v1/saved-questions?connection_id=...&search=...&cursor=...&limit=... returns {items,next_cursor}; GET /{saved_question_id} returns typed definition/revision/parameters. Bound search, payloads, and page size (1..100).
- PATCH /{saved_question_id} requires expected_revision; accepts definition metadata/parameter metadata/chart preference or explicit successful replacement_query_id. Revalidate selected slots. A stale revision returns 409; never regenerate implicitly.
- POST /{saved_question_id}/duplicate {title} creates an independent revision-1 definition after current authorization. DELETE removes only the definition.
- POST /{saved_question_id}/run {parameters, expected_revision} snapshots that revision into a new run, resolves values at worker start, revalidates dependencies, and uses direct execution. Retain supplied values/resolved dates only in query history, excluded from general logs.
- Natural-language creation accepts parent_query_id. Check parent/ancestor eligibility before queueing and again in worker. Foreign parent: 404; incomplete/wrong-connection parent: 422; stale/oversized context: 409 with safe actionable error. Parent deletion does not erase independent child context; deleted parents cannot be selected anew.
- Completed responses retain existing fields and add typed origin, parent/source/saved IDs and revision, authorized context, optional presentation, and results_expires_at. Presentation is absent when rows are unavailable. History includes origin/relationship/revision fields, no rows. CSV stays cache-authorized and returns 410 after eviction/expiry.

## Execution Order and Verification Convention

Execute **1 -> 2 -> 4 -> 5 -> 6 -> 7 -> 8 -> 3 -> 9 -> 10 -> 11 -> 12 -> 13**. Task numbers retain their original feature identity. Consumers must not depend on undeclared interfaces deferred to Task 13.

Each future implementation task follows its unchecked red/green steps, then a scoped commit after passing verification. Editing this plan does not complete an implementation checkbox. Do not commit implementation in this documentation session.

Backend commands below run from apps/api in the installed environment; frontend commands run from repository root. Redirect verbose output to a unique temporary log, inspect exit codes, report one success line, and print only relevant failure excerpts. Use the same discipline for builds.

Live-source tests use disposable local/CI fixtures. Missing credentials may skip locally but fail the required CI engine gate; skips are not compatibility evidence. Real migration tests use disposable PostgreSQL metadata, not application production data.

Task 1 adds analytics_env: a real TestClient with valid owner cookies/CSRF, owner/foreign users, visible/foreign connections, and persisted snapshots. completed_run creates a completed owner run with validated metadata/cache without source I/O. Isolate/restore settings, engine, cache, provider, and admission singletons; provider/executor spies are explicit per test. Do not accept 401/403 as proof of SQL validation.

## Review Focus

| Failure condition | Test owner |
| --- | --- |
| Tampered/missing bindings; quote/Unicode/percent values; placeholder survival through probes/wrappers | Task 6: token negatives and both real-driver roundtrips |
| Policy/semantic mutation while queued/executing; cancellation racing with publication | Task 5 lifecycle; Tasks 7/8 dependency drift |
| Injected fetch limit becomes permanent author cap or smaller author limit is raised | Tasks 5/6/7 provenance and rerun tests |
| Numeric strings/nulls/empty or duplicate dates/mixed units/eviction mislead chart or explanation | Tasks 4/9 precision, fallback, expiry |
| Failed follow-up/connection change uses wrong parent or discards draft | Tasks 10/12 full workspace tests |

---

### Task 1: Persistence, Domain Context, and Repository Contracts

**Dependencies:** None.

**Files:**
- Create: apps/api/src/querylens/domain/analytics.py; apps/api/migrations/versions/0003_everyday_analytics.py; apps/api/tests/unit/test_analytics_repository.py; apps/api/tests/integration/test_everyday_analytics_migration.py.
- Modify: apps/api/src/querylens/persistence/tables.py; apps/api/src/querylens/persistence/repositories/query_runs.py; apps/api/src/querylens/persistence/repositories/history.py; apps/api/src/querylens/persistence/retention.py; apps/api/tests/conftest.py; apps/api/tests/integration/test_migrations.py; apps/api/tests/integration/test_history.py; docs/CONTRACTS.md.

**Interfaces:** Produce shared strict context models plus BoundParameter/ResolvedParameters declarations above, with no driver behavior yet. Extend QueryRunRepository.create(..., origin="natural_language", parent_query_id=None, source_query_id=None, saved_question_id=None, saved_question_version=None, submitted_sql=None, saved_definition_json=None) compatibly. Add complete(query_id: str, context: RunContext, canonical_sql: str, assumptions: list[str], warnings: list[str], truncated: bool) -> bool: one atomic metadata/terminal update guarded against terminal states. Existing update_state remains for stages/errors.

- [ ] **1. Write failing repository/schema/migration tests.** Assert complete writes context and completed atomically, increments state_version once, and returns false after cancellation without modifying metadata. Old create callers retain defaults. Context JSON roundtrips preserve types/versions and reject result-row fields. Add the shared HTTP fixtures defined above.
- [ ] **2. Run red:** python -m pytest tests/unit/test_analytics_repository.py tests/integration/test_everyday_analytics_migration.py -q. Confirm missing interface/schema failures rather than auth/fixture/credential errors.
- [ ] **3. Add explicit DDL and matching metadata.** Revision 0003_everyday_analytics revises 0002_review_hardening; never import mutable application metadata for migration operations.
  - connections.semantic_version: non-null integer default 1.
  - query_runs: constrained origin; nullable parent/source FKs with named ON DELETE SET NULL; saved ID/version without a deletion-blocking FK; nullable submitted_sql, saved_definition_json, run_context_json Text; nullable snapshot_hash, policy_version, semantic_version. Old rows remain readable; legacy runs without version/context cannot be follow-up parents until rerun.
  - catalog_labels: ID, connection cascade FK, physical namespace/table/optional column, display name/description, version, timestamps. Separate unique partial indexes for table targets (column_name IS NULL) and column targets (IS NOT NULL), in PostgreSQL and SQLite metadata. Never default a MySQL namespace to public.
  - saved_questions: ID, connection/user cascade FKs, title/description, authorized canonical template, effective question, parameter definitions/defaults JSON, default_max_rows, chart preference, referenced-object signatures JSON, metric/label references JSON, source snapshot/policy/semantic versions, author limit, revision, timestamps. Use Text JSON with typed service validation. Index owner/connection/cursor and new parent/source references.
  - Implement serialization and guarded completion. Run retention deletes run-local context/supplied parameters independently of saved definitions. Defaults/choices remain saved-definition data.
- [ ] **4. Verify actual migration behavior.** On disposable PostgreSQL, upgrade to 0002, seed an old run, upgrade to head, inspect constraints/indexes/defaults, downgrade to 0002, re-upgrade, and compare metadata shape. Test duplicate table-label targets, connection cascades, saved deletion retaining audit IDs, and parent deletion/retention preserving child context. Enable SQLite FKs for cascade tests. Replace the hardcoded ten-table assertion with the declared expected table set. Run focused tests plus existing migration/history tests.
- [ ] **5. Update C04/C08/C09 and commit verified scoped changes.** Describe legacy-read behavior and do not synthesize historical provenance.

### Task 2: Catalog Labels, Metric Editing, Retrieval, and Semantic Versions

**Dependencies:** Task 1.

**Files:**
- Create: apps/api/src/querylens/semantics/labels.py; apps/api/src/querylens/semantics/versions.py; apps/api/src/querylens/api/labels.py; apps/api/tests/unit/test_catalog_labels_and_synonyms.py; apps/api/tests/integration/test_analytics_semantics.py.
- Modify: apps/api/src/querylens/semantics/metrics.py; apps/api/src/querylens/api/metrics.py; apps/api/src/querylens/pipeline/context.py; apps/api/src/querylens/retrieval/schema_ranker.py; apps/api/src/querylens/main.py; docs/CONTRACTS.md.

**Interfaces:** Implement labels and metric PATCH contracts above. Declare SemanticContext in semantics/versions.py; load_semantic_context(user_id: str, snapshot: CatalogSnapshot) -> SemanticContext supplies visible labels, enabled validated metrics/versions, and semantic_version. normalize_alias(value: str) -> str uses Unicode NFKC, collapsed whitespace, casefold. Physical identifiers retain engine-sensitive spelling. Context/ranker accept optional semantic context compatibly.

- [x] **1. Write failing semantic/API tests.** A synonym-only question retrieves the metric/table and its complete DSL; labels participate in retrieval/generation while physical SQL identifiers remain unchanged. Conflicting normalized enabled keys/names/synonyms return 409. Disabling a definition resolves its alias conflict. Hidden definitions never enter delivery/prompts. Duplicate table display names conflict within a namespace; duplicate column display names conflict within a table, separately from table-label names.
- [x] **2. Run red:** python -m pytest tests/unit/test_catalog_labels_and_synonyms.py tests/integration/test_analytics_semantics.py -q.
- [x] **3. Implement owner-scoped reads and atomic writes.** Lock connection row, validate current catalog, check expected versions/conflicts against existing definitions, write and increment semantic_version in one transaction. Metric DSL/enabled changes increment metric version; deletion advances semantic_version. Bound synonyms to 20 nonempty entries of <=100 characters and descriptions/display names to documented sizes. GET filters hidden targets; visible PUT preserves hidden records internally without exposing them.
- [x] **4. Verify API/security/retrieval.** Add CSRF negatives, owner/foreign 404s, concurrent-version conflicts, MySQL namespace labels, hash/version stability, and legacy DSL loading with empty synonyms. Run focused tests plus tests/unit/test_metrics.py and tests/integration/test_retrieval.py. Document semantic-versus-physical version separation in C05/C10.
- [x] **5. Export new OpenAPI, update corresponding TypeScript contracts, and commit verified changes.** Task 13 is the final parity gate.

Implemented on `feat/everyday-analytics-persistence`; verification and API behavior are recorded in `docs/CONTRACTS.md` (Task 2).

### Task 3: Business Labels and Complete Structured Metric Editor

**Dependencies:** Tasks 1/2.

**Files:**
- Create: apps/web/src/features/schema/LabelManager.tsx; apps/web/src/__tests__/labels_and_synonyms.test.tsx.
- Modify: apps/web/src/api/client.ts; apps/web/src/api/catalog.ts; apps/web/src/features/schema/MetricEditor.tsx; apps/web/src/features/schema/Metrics.tsx; apps/web/src/features/schema/SchemaExplorer.tsx; apps/web/src/features/schema/TableDetails.tsx.

**Interfaces:** Add api.put<T>(path: string, body: unknown): Promise<T> through existing CSRF request code. LabelManager({connectionId,tables,onSaved}) loads labels/version and saves with expected_semantic_version. MetricEditor accepts optional existing metric/version and catalog; POST creates and PATCH updates with expected_version.

- [x] **1. Write failing HTTP-boundary UI tests.** Load labels, change table/column names/descriptions, submit exact PUT/version, reload persisted values, and retain drafts on 409/422. Create/edit metric synonyms/description/units/aggregation/filters/grain and assert full DSL/PATCH version. Use authorized catalog selectors for physical objects.
- [x] **2. Run red:** npm test --prefix apps/web -- src/__tests__/labels_and_synonyms.test.tsx.
- [x] **3. Implement controls and labels.** Keep physical names inspectable. Support existing aggregations including count_distinct and structured filter operators; no arbitrary SQL. Ignore/abort stale connection requests and update versions after save.
- [x] **4. Verify focused tests and npm run typecheck --prefix apps/web.** Assert PUT credentials/client header/CSRF, server error feedback, and connection switching preventing stale labels from replacing current form data.
- [x] **5. Commit verified UI/client changes.**

### Task 4: Verified Run Context and Cache-Bound Presentation

**Dependencies:** Tasks 1/2. Provides completion context/presentation for Task 5 and subsequent origins.

**Files:**
- Create: apps/api/src/querylens/domain/presentation.py; apps/api/src/querylens/pipeline/intent.py; apps/api/src/querylens/pipeline/explanation.py; apps/api/tests/unit/test_presentation_and_charts.py; apps/api/tests/integration/test_presentation_delivery.py.
- Modify: apps/api/src/querylens/api/query_schemas.py; apps/api/src/querylens/api/queries.py; apps/api/src/querylens/api/history.py; apps/api/src/querylens/jobs/results.py; apps/api/src/querylens/semantics/metrics.py.

**Interfaces:** build_run_context(template_sql: str, author_limit: int | None, question: str, origin: RunOrigin, snapshot: CatalogSnapshot, semantics: SemanticContext, resolved_parameters: ResolvedParameters | None = None) -> RunContext. derive_presentation(columns, rows, context: RunContext, origin: RunOrigin, truncated: bool) -> PresentationMetadata. PresentationMetadata contains typed title/explanation/chart_type/x_column/y_column/date scope/verified definitions and units/warnings. Add ResultCache.get_entry(query_id, snapshot_hash=None) -> CacheEntry | None while retaining get; derive UTC results_expires_at from remaining TTL without extending it.

- [x] **1. Write failing context/presentation/delivery tests.** Assert exact integer/Decimal strings, zero/all-null rows, 51 points, multiple measures, mixed units, duplicate keys, unsorted dates, unsafe precision/magnitude, and visible truncated warnings. Manual SQL cannot claim original business meaning. Real completed-run GET must return new typed fields; a schema declaration is insufficient.
- [x] **2. Run red:** python -m pytest tests/unit/test_presentation_and_charts.py tests/integration/test_presentation_delivery.py -q.
- [x] **3. Produce context and conservative recommendations.** Derive references/filters from the validated template AST. Recognize a metric only for a supported exact structured aggregation/filter/grain match; retrieval or wording is not proof. Unsupported SQL receives neutral meaning and no asserted metric use. Persist a self-contained effective description with verified scope and canonical SQL fallback; do not add a model call over rows or an unvalidated candidate-schema extension.
  - A single value needs one non-null numeric cell. Line/bar need exactly two compatible columns, unique valid keys, 1..50 points, and precision-safe conversion. Sort temporal plotting points, never table rows. Unknown currency stays unlabeled; conflicting known units or unsupported shapes fall back.
  - Define one explicit plotting rule shared with frontend tests: integers beyond JS safe range fall back; Decimal strings must roundtrip through finite JS-number-compatible representation without changing their exact decimal value or collapsing distinct values. Uncertain conversion falls back. Keep exact strings in table/KPI.
- [x] **4. Integrate actual authorized delivery.** get_query explicitly maps origin/context and derives presentation only from a currently authorized cache entry. Filter historical labels/metrics by current catalog. On TTL/memory eviction or policy invalidation, omit rows/presentation/expiry and return results_available:false; persist no row-derived explanation. History maps lineage/origin. Tests cover foreign access, hidden references, lifetime, and CSV 410. Run focused tests plus history/CSV regressions.
- [x] **5. Export typed completed/history additions and commit.** Preserve optional/defaulted legacy behavior and status discriminators.

### Task 5: Shared Execution Lifecycle and Manual SQL

**Dependencies:** Tasks 1/2/4.

**Files:**
- Create: apps/api/src/querylens/pipeline/lifecycle.py; apps/api/src/querylens/pipeline/direct.py; apps/api/tests/integration/test_manual_sql_execution.py; apps/api/tests/integration/test_analytics_lifecycle.py.
- Modify: apps/api/src/querylens/pipeline/orchestrator.py; apps/api/src/querylens/sql/policy.py; apps/api/src/querylens/domain/query.py; apps/api/src/querylens/api/queries.py; apps/api/src/querylens/pipeline/classifier.py; apps/api/tests/integration/test_cancellation.py; docs/CONTRACTS.md.

**Interfaces:** Produce ValidatedArtifact and validate_query_artifact above. run_with_lifecycle(query_id,user_id,connection_id,reservation,process: Callable[[RunServices],Awaitable[None]]) -> None owns lease/deadline/errors/cleanup/task deregistration. RunServices.execute(token) -> QueryResult retains current _execute_source behavior and remaining-time limits; RunServices.publish(artifact,result,context,assumptions,warnings) -> bool rechecks current owner/catalog/semantics and calls atomic completion. run_manual_sql_pipeline(...,sql,source_query_id,max_rows,reservation) -> None uses no provider. Keep existing run_query_pipeline signatures/defaults/provider injection compatible.

- [x] **1. Write failing authenticated endpoint/lifecycle tests.** Valid POST returns 202 then completed, actual bounded SQL, origin/source, and zero provider/repair calls. Unsafe writes/multiple statements/hidden identifiers/locks/functions become rejected with zero executor calls. CSRF/auth negatives are separate tests, not substitutes for SQL validation.
- [x] **2. Run red:** python -m pytest tests/integration/test_manual_sql_execution.py tests/integration/test_analytics_lifecycle.py -q.
- [x] **3. Extract common lifecycle without changing generation semantics.** Keep generation/repair in orchestrator; direct paths skip them entirely. Authorize completed same-connection source before admission and again in worker. Enforce configured row limits before acceptance and UTF-8 SQL bounds before validation/execution. Record submitted draft separately and direct-attempt diagnostics accurately.
- [x] **4. Preserve lifecycle and delivery guarantees.** Activate lease before work, retain until DBAPI cleanup finishes; preserve bounded workers, socket cancellation, shutdown registration, all deadlines, semantic warnings, current catalog/semantic publication checks, terminal guards, and cache eviction after a lost completion race. Test overload, queued/in-flight cancellation, restart interruption, lowered budgets, source mismatch, drift during execution, no permanently queued exceptions, and old natural-language compatibility. Run pipeline/vertical-slice/cancellation/load-budget regressions.
  - Provenance assertions: no author limit + request 100 stores author_limit=null with executable LIMIT 101; explicit LIMIT 20 stores 20. A future filter cannot raise that cap.
- [x] **5. Update C01/C06/C07/C08 for authenticated manual SQL, export contracts, and commit verified changes.** Replace obsolete endpoint exclusions explicitly while retaining source security boundaries.

### Task 6: Parameter Slots, Immutable Tokens, and Both Driver Bindings

**Dependencies:** Tasks 1/5.

**Files:**
- Create: apps/api/src/querylens/sql/parameters.py; apps/api/src/querylens/sql/bindings.py; apps/api/tests/unit/test_sql_parameters.py; apps/api/tests/integration/test_parameter_execution.py.
- Modify: apps/api/src/querylens/domain/query.py; apps/api/src/querylens/sql/policy.py; apps/api/src/querylens/sql/limits.py; apps/api/src/querylens/execution/executor.py; apps/api/src/querylens/execution/bounds.py; apps/api/src/querylens/execution/postgres.py; apps/api/src/querylens/execution/mysql.py; apps/api/src/querylens/pipeline/direct.py; apps/api/tests/integration/test_execution.py; docs/CONTRACTS.md.

**Interfaces:** Implement ParameterDefinition/Target, extraction, compilation, fingerprint, and driver APIs defined above, using Task 1's BoundParameter/ResolvedParameters models. ResolvedParameters has validated supplied values, immutable typed bindings, exact dates, and effective max_rows. Empty bindings preserve current factory/validator callers.

- [x] **1. Write failing safety tests.** Selected values must be absent from SQL and present in typed driver bindings; only the selected predicate changes. Reject forged/duplicate/unknown targets, stale template fingerprint, bool/string counts, reversed/invalid dates, type-mismatched membership, unsupported scopes/positions, and unresolved placeholders. Mutation of an input mapping after minting cannot change the token; copied/altered SQL/bindings/connection/limits fail before source/credential access.
- [x] **2. Run red:** python -m pytest tests/unit/test_sql_parameters.py tests/integration/test_parameter_execution.py -q. Skipped real-engine cases do not satisfy the driver gate.
- [x] **3. Implement extraction and typed AST compilation.** Resolve and recheck canonical targets; date-only ends, DATE/timestamp values, defaults, fixed dates, this_month/this_year, UTC execution-time boundaries. Inject a clock for month/year transition tests. Accept legitimate author-allowed SQL-looking strings safely; rejecting an unlisted injection is not a driver-binding proof. Apply result count through literal AST limits and author/configured caps.
- [x] **4. Change token verification and both drivers together.** Revalidate exact placeholder sets/canonical AST, compile metadata and guarded SQL after transforms, and bind both executions. Test PostgreSQL/MySQL actual returned rows/types for quotes, Unicode, percent literals/LIKE, dates, decimals, empty bindings, and malicious-looking allowed strings. Assert metadata-probe and streamed-result bindings, read-only settings, cancellation, sentinel truncation, and no value interpolation. Run existing AST/execution/security/authorization suites plus new tests.
- [x] **5. Document immutable bindings in C06 and commit verified changes.** A mutable binding dict or AST literal insertion does not satisfy this task.

### Task 7: Saved Definitions, Revisioned CRUD, and Direct Reruns

**Dependencies:** Tasks 1/2/4/5/6.

**Files:**
- Create: apps/api/src/querylens/persistence/repositories/saved_questions.py; apps/api/src/querylens/semantics/saved_questions.py; apps/api/src/querylens/api/saved_questions.py; apps/api/tests/integration/test_saved_questions_api.py.
- Modify: apps/api/src/querylens/api/queries.py; apps/api/src/querylens/api/query_schemas.py; apps/api/src/querylens/pipeline/direct.py; apps/api/src/querylens/main.py; docs/CONTRACTS.md.

**Interfaces:** Implement discovery/saved HTTP contracts above. SavedQuestionRepository.create(record), get(id,user_id), list_for_connection(connection_id,user_id,search,cursor,limit), update(id,user_id,expected_revision,changes), delete(id,user_id) persist real owner-scoped records. validate_saved_dependencies(definition,snapshot,semantics) -> None compares referenced signatures/metrics and revalidates policy. run_saved_question_pipeline(query_id,user_id,connection_id,definition_snapshot,supplied_values,reservation) -> None uses shared lifecycle and parameter compilation, never generation.

- [x] **1. Write failing authenticated persistence/API journeys.** Create from completed run, reload/search, discover/select slots, update revision, duplicate, rerun changed filters, delete. Assert exact rows, origin, saved ID/revision, supplied/resolved values, and zero provider/repair calls. Reject foreign resources, incomplete sources, forged SQL/slots, invalid CSRF, stale revision, and unknown values. Do not substitute a build_record dictionary test.
- [x] **2. Run red:** python -m pytest tests/integration/test_saved_questions_api.py -q.
- [x] **3. Implement revisioned definitions and execution.** Server reconstructs source template/context and validates submitted slot/default/choice data. Capture one revision/dependency snapshot atomically at acceptance; later definition edits/deletion cannot change the accepted template. Worker rechecks connection/dependencies and resolves values at run start. Persist audit data independent of definition deletion, exclude parameters from general logs, and never silently regenerate.
- [x] **4. Verify drift/deletion/limits.** Unrelated changes succeed after validation; referenced object/type/metric changes require review; revocation prevents execution/delivery. Connection deletion cascades definitions; definition deletion retains historical runs; history retention removes run-local parameters. Explicit LIMIT 20 stays capped; originally requested 100 with no author limit can rerun at 200 with a 201 fetch sentinel. Test queued edits/deletion, concurrent revisions, lower configuration, paging, and explicit successful replacement.
- [x] **5. Update C09/C10, export typed APIs, and commit verified changes.**

### Task 8: Authorized Follow-Up Lineage and Prompt Budget Integration

**Dependencies:** Tasks 1/2/4/5; Task 7 permits testing saved-run parents.

**Files:**
- Create: apps/api/src/querylens/pipeline/followup.py; apps/api/tests/unit/test_followup_lineage.py; apps/api/tests/integration/test_followup_context.py.
- Modify: apps/api/src/querylens/api/queries.py; apps/api/src/querylens/pipeline/orchestrator.py; apps/api/src/querylens/pipeline/context.py; apps/api/src/querylens/pipeline/repair_context.py; apps/api/src/querylens/llm/live.py; docs/CONTRACTS.md.

**Interfaces:** resolve_followup_context(parent_query_id: str,user_id: str,connection_id: str,current_snapshot: CatalogSnapshot,semantics: SemanticContext,current_question: str,max_tokens: int=2000) -> FollowUpContext. Contains <=5 chronological authorized turns, latest self-contained context, required references, formatted text, estimated_tokens. Add optional parent_query_id to run_query_pipeline and followup_context to context/repair assembly compatibly.

- [x] **1. Write failing stored-lineage tests.** Completed/failed/foreign/wrong-connection/deleted/legacy parents, cycles, ancestor authorization, selected-parent branches, expired cache with retained context, and physical/policy/semantic drift. Six turns retain latest five plus latest self-contained intent. Oversized required context errors using the actual byte estimator; no invented tokenizer assumption.
- [x] **2. Run red:** python -m pytest tests/unit/test_followup_lineage.py tests/integration/test_followup_context.py -q.
- [x] **3. Integrate before schema selection.** Validate parent before admission and again in worker; authorize every included ancestor and connection, never unscoped repo.get. Deleted older ancestors stop traversal while retained self-contained parent context remains authoritative. Reject cycles/inconsistent ancestry. Include no rows, row-derived explanations, secrets, or unverified manual business meaning. Persist new resolved context independently.
- [x] **4. Reserve total prompt budget including repairs.** Reserve follow-up bytes before schema retrieval; include inherited required objects even for low-information fragments. Reject if essential context/schema cannot fit. Retain selected parent context through repair and count instructions/question/schema/follow-up/repair against input/cumulative limits without increasing generation or total deadlines. Provider spies assert exact inherited scope and absence of rows in both initial and repair prompts. Test manual/saved parents and existing safe ambiguity rejection.
- [x] **5. Update follow-up contracts, export types, and commit verified changes.**

### Task 9: Accessible Answer Rendering and Expiry-Aware Charts

**Dependencies:** Tasks 4/5. Task 10 extends execution state after this presentation integration.

**Files:**
- Create: apps/web/src/features/workspace/AnswerPresentation.tsx; apps/web/src/features/workspace/charts/AccessibleChart.tsx; apps/web/src/features/workspace/charts/plotValues.ts; apps/web/src/__tests__/answer_presentation.test.tsx.
- Modify: apps/web/src/features/workspace/WorkspaceView.tsx; apps/web/src/features/workspace/ResultsTable.tsx; apps/web/src/features/workspace/Assumptions.tsx.

**Interfaces:** AnswerPresentation({run: PublicRunCompleted,onRerun}) uses typed context/presentation and available rows. AccessibleChart({presentation,columns,rows}) renders validated plot values and exact accessible text. Frontend numeric eligibility follows Task 4 rules; any mismatch falls back to table.

- [x] **1. Write failing rendering/interaction tests.** Answer-first order, collapsed SQL, visible warnings, chart/table switch, keyboard/ARIA behavior, exact KPI/table strings, and fallback for 51 points, unsafe numbers, null/empty values, mixed units, duplicate keys, or incompatible saved preferences. Assert plotted meaning/data, not SVG presence alone.
- [x] **2. Run red:** npm test --prefix apps/web -- src/__tests__/answer_presentation.test.tsx.
- [x] **3. Implement conservative SVG.** Keep every eligible <=50 point, chronological line scale, axes, labels, exact accessible tooltips/text, and markers/patterns. No sampling/aggregation/currency guessing. Keep existing table and warnings in either view; apply preferences only when compatible.
- [x] **4. Add expiry/revalidation behavior.** At results_expires_at clear rows/chart/KPI/result-derived explanation, disable CSV, and re-fetch availability. Revalidate completed runs on focus and periodic refresh no more than once per 30 seconds to discover early eviction/revocation. Clear protected data on authorization failure. Preserve permitted immutable metadata and offer origin-appropriate rerun. Fake-timer tests cover expiry, early eviction with unchanged state_version, and revocation. Availability changes must not be discarded by state_version-only comparison. Run focused tests/typecheck.
- [x] **5. Commit verified presentation changes.**

### Task 10: Workspace Selection State and Integrated SQL Editing

**Dependencies:** Tasks 5/9.

**Files:**
- Create: apps/web/src/__tests__/editable_sql_panel.test.tsx; apps/web/src/__tests__/workspace_execution.test.tsx.
- Modify: apps/web/src/features/workspace/SQLPanel.tsx; apps/web/src/features/workspace/WorkspaceView.tsx; apps/web/src/features/workspace/QuestionForm.tsx; apps/web/src/features/history/History.tsx; apps/web/src/App.tsx.

**Interfaces:** SQLPanel({sql,dialect,origin,runId,onRunSql,disabled}); onRunSql(draft: string) -> Promise<void>. Separate selectedRunId, inFlightRunId, selectedParentId, lastSuccessfulRunId, loaded run metadata, and draft keyed by run. All origins share accepted-run handling/polling through current navigation callbacks.

- [ ] **1. Write failing workspace tests.** Edit/run asserts exact connection/source/max_rows and polls the accepted run, then shows actual bounded SQL. Reset/close/navigation/connection changes require dirty-draft confirmation; cancellation preserves draft. Mock confirmation explicitly. Failed manual execution leaves prior successful answer selectable.
- [ ] **2. Run red:** npm test --prefix apps/web -- src/__tests__/editable_sql_panel.test.tsx src/__tests__/workspace_execution.test.tsx.
- [ ] **3. Wire editor through the real endpoint.** Keep executed SQL immutable and textarea draft separate. Origin-aware "Edited SQL" labels, dialect, pending state, safe errors, and api.post manual submission. Abort stale reads; earlier completions cannot change current selection/connection. Protect drafts across all discard actions, not just reset.
- [ ] **4. Verify integration and existing workspace tests.** Selected-run reset, rejection, cancellation, retry, history navigation, connection switch, out-of-order responses, diagnostics, and old terminal variants. Run focused tests, existing phase_08 workspace tests, and frontend typecheck.
- [ ] **5. Commit verified workspace/editor changes.**

### Task 11: Saved Questions and Typed Filter Controls

**Dependencies:** Tasks 6/7/9/10.

**Files:**
- Create: apps/web/src/features/workspace/SavedQuestionsModal.tsx; apps/web/src/features/workspace/SavedQuestionsManager.tsx; apps/web/src/features/workspace/SavedQuestionFilters.tsx; apps/web/src/__tests__/saved_questions_view.test.tsx.
- Modify: apps/web/src/features/workspace/WorkspaceView.tsx; apps/web/src/api/generated/schema.ts as contracts evolve.

**Interfaces:** Save modal consumes sourceQueryId and server-discovered definitions/template_fingerprint, not authoritative client SQL. Manager receives connectionId and shared onRunAccepted(query_id). Filters use typed values and expected_revision; date presets are this_month/this_year and resolved exact dates come from the completed response.

- [ ] **1. Write failing HTTP-backed UI journeys.** Discover/select slots, configure labels/defaults/category options, save/reload, search/page/detail, edit/duplicate/delete, run changed values, and display polled result. Assert actual typed payloads, revision, and resolved dates. Test no-filter saves, invalid values, conflicts, and review-required errors.
- [ ] **2. Run red:** npm test --prefix apps/web -- src/__tests__/saved_questions_view.test.tsx.
- [ ] **3. Implement typed controls.** Display readable and inspectable physical references, inclusive date-end/UTC explanation, author count cap, and configured maximum. Do not stringify numeric/bool category values. Client validation aids entry; server is authoritative.
- [ ] **4. Add explicit review/update and variation flows.** Review produces a new successful run; replacing a definition requires explicit revision action. Ask a variation never mutates stored SQL. Connection changes clear/abort old definition state. Test origin-appropriate expired reruns, errors, pending states, focus/keyboard behavior, and isolation. Run focused tests/typecheck.
- [ ] **5. Commit verified saved-question UI.**

### Task 12: Follow-Up Selection, Branching, and Failure Recovery

**Dependencies:** Tasks 8/9/10/11.

**Files:**
- Create: apps/web/src/features/workspace/FollowUpBar.tsx; apps/web/src/__tests__/followup_workflow.test.tsx.
- Modify: apps/web/src/features/workspace/WorkspaceView.tsx; apps/web/src/features/history/History.tsx; apps/web/src/App.tsx.

**Interfaces:** FollowUpBar({parent: PublicRunCompleted,onSubmit(question,parentQueryId),onStartNewQuestion,disabled}) shows selected parent and authorized filters. Reuse selected-parent state and history/retained-answer selection, never the last-completed request implicitly.

- [ ] **1. Write failing full-workspace branching tests.** Complete A, follow up B, select A, submit C, assert C uses A's ID/scope. Fail B and retain A. Start-new clears parent; connection change clears protected context after draft confirmation. Test manual/saved/expired-row parents, stale/foreign/incomplete errors, aborts, and out-of-order replies.
- [ ] **2. Run red:** npm test --prefix apps/web -- src/__tests__/followup_workflow.test.tsx.
- [ ] **3. Implement selected-parent workflow.** Successful parent stays independent of failed/in-flight child. Show inherited scope before submit and resolved filters afterward. Stale/oversized context offers an explicit standalone-question action; no silent fallback or clarification wizard. Use shared accepted-run polling.
- [ ] **4. Verify through workspace/history navigation, not callback-only tests.** Include standalone requests, connection reset, and expired-row metadata eligibility. Run focused/workspace tests and typecheck.
- [ ] **5. Commit verified branching UI.**

### Task 13: Contract Parity and Complete Feature Acceptance Gates

**Dependencies:** All preceding tasks in dependency order.

**Files:**
- Create: apps/api/tests/integration/test_everyday_analytics_e2e.py; apps/api/tests/unit/test_analytics_contracts.py; apps/web/src/__tests__/analytics_contracts.test.ts.
- Create: packages/contracts/fixtures/everyday_analytics.json with representative request/status/parameter/presentation families, used by both backend and frontend contract tests.
- Modify: scripts/export_schema.py; packages/contracts/openapi.json; apps/web/src/api/generated/schema.ts; .github/workflows/ci.yml; .github/workflows/security.yml; scripts/verify.ps1; docs/CONTRACTS.md; docs/development.md; docs/security.md; docs/limitations.md.

**Interfaces:** Add exporter --check to compare deterministic JSON bytes without writing. There is no current TypeScript generator: retain the explicit contract module for this increment, document that accurately, and add parity checks. Shared JSON fixtures are validated against backend models and compared with frontend typed fixtures declared using TypeScript satisfies; negative type assertions verify status narrowing and parameter/date unions. Backend tests check exact requiredness/enums/constraints. Do not cast imported JSON to a desired contract to hide incompatibility. No broad casts or dict[str,Any] presentation types.

- [ ] **1. Write failing acceptance/contract tests.** Compare deterministically serialized live OpenAPI to checked-in bytes, verify requests/responses, and execute authenticated HTTP/polling journeys for natural-language answer, manual edit, save/filter rerun, synonym retrieval, and branching. Assert intended data, origins, lineage, versions, warnings, and no provider calls on direct paths. Route names alone prove none of these.
- [ ] **2. Run red:** python -m pytest tests/unit/test_analytics_contracts.py tests/integration/test_everyday_analytics_e2e.py -q. Wrong behavior/stale contracts must fail independently of auth setup.
- [ ] **3. Synchronize and document.** From root run python scripts/export_schema.py; explicitly update TypeScript/fixtures, then python scripts/export_schema.py --check. Correct the existing generated-file comment claiming this script emits TypeScript. Document endpoint authorization/read-only safety, binding guarantees, neutral meaning, unsupported-filter fallback, UTC, drift/revision review, private ownership, volatile results, and follow-up budgets. Replace obsolete endpoint exclusions only where the new authenticated contract supersedes them; retain source network restrictions.
- [ ] **4. Run required logged gates.** From apps/api: python -m pytest tests/unit tests/integration tests/security -q. From root: npm test --prefix apps/web; npm run typecheck --prefix apps/web; npm run build --prefix apps/web. Run actual Alembic roundtrip against disposable PostgreSQL metadata and positive/negative manual and parameterized source journeys against PostgreSQL and Oracle MySQL. CI provisions fixtures and fails missing required engine cases; report advertised-version coverage honestly. Retain raw/tampered token, SQL authorization, cancellation, ownership, retention/history, CSV, budget, and frontend regression gates. Investigate failures without weakening assertions or omitting security/integration suites.
- [ ] **5. Reconcile evidence and commit final verified contracts/docs.** Record commands/exit codes and local skips. No completion claim while a task or required engine/contract gate remains unfinished. The present plan-only revision needs documentation checks, not application test execution.

## Acceptance Matrix and Handoff

| Outcome | Owners and evidence |
| --- | --- |
| Labels/metrics/synonyms affect authorized generation | Tasks 2/3: retrieval, conflict, complete DSL, HTTP tests |
| Answer-first charts and honest deterministic explanation | Tasks 4/9: exact values, safe shapes, visible warnings, expiry |
| Independent manual runs preserve source safety without repair | Tasks 1/5/10: authenticated execution, zero-provider, lifecycle |
| Typed reusable filters and revisioned reruns | Tasks 6/7/11: immutable token, both drivers, actual data, revisions/drift |
| Bounded context and selected-parent branching | Tasks 8/12: inspected prompts, total budgets, workspace recovery |
| Migration/retention/current permissions/API compatibility | Tasks 1/4/5/13 and existing security/integration suites |

Revision self-review: all thirteen original feature tasks remain represented; repository/lifecycle/binding dependencies precede consumers; new interfaces have owning tasks; semantic provenance and historical delivery have explicit rules; each review-focus failure has a test owner. At plan authoring, implementation was unstarted and every implementation checkbox was unchecked; task-local checkboxes now track subsequent implementation.

This document is the revised plan for review. Product implementation, execution-method selection, commits, and deployment are separate work and are not performed by this documentation update.
