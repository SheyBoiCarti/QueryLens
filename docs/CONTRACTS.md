# Analytics contracts

This document records Everyday Analytics persistence, semantic metadata and
editing, verified presentation, and shared/manual execution (Tasks 1–5).
Parameter compilation, saved-question workflows, and follow-ups remain owned by
subsequent tasks in the implementation plan.

## C04 — Metadata schema and migrations

Production metadata uses PostgreSQL. Alembic revision
`0003_everyday_analytics`, following `0002_review_hardening`, uses explicit DDL
independent of application metadata. SQLAlchemy metadata and migrations declare
matching columns, defaults, constraints, foreign keys, and indexes. SQLite
repository tests enable foreign keys when verifying deletion semantics.

Connections have separate `policy_version` and `semantic_version` integers,
initially 1. Semantic mutations advance the latter; neither historical query
context nor physical snapshot hashes are rewritten by that change.

`catalog_labels` records a physical namespace, table, optional column, display
name, description, version, and timestamps. The namespace is mandatory and has
no default: MySQL database names must never be replaced by `public`. Unique
partial indexes separately enforce one table label per connection/namespace/table
and one column label per connection/namespace/table/column. Connection deletion
cascades to labels.

`saved_questions` stores private owner/connection-scoped definitions: title,
description, authorized canonical SQL template, effective question, parameter
definitions and defaults, default row count, optional chart preference, referenced
object/type signatures, metric and label references, source snapshot/policy/semantic
versions, original author limit, revision, and timestamps. JSON uses Text columns;
services must validate it against typed contracts before writing. An index on
owner/connection/created-at/ID supports scoped cursor pagination. Owner or
connection deletion cascades to definitions. No saved definition contains source
rows or computed answers.

## C08 — Run context, lineage, and atomic completion

`QueryRunRepository.create` retains its existing positional arguments and defaults
to `origin="natural_language"`. Origins are constrained to `natural_language`,
`follow_up`, `manual_sql`, and `saved_question`. New optional metadata records
parent/source IDs, saved-question ID/revision, submitted SQL, and an accepted
saved-definition snapshot. Parent/source foreign keys are named and use
`ON DELETE SET NULL`. Their indexes support lineage lookups. Saved-question
ID/revision are audit values without a foreign key, so deleting a definition
cannot delete or block historical runs.

`RunContext` and its physical-object, metric, label, and applied-filter references
are strict frozen models. Collections are immutable tuples. They record a
self-contained effective question, authorized canonical template, original author
limit, filters, referenced types/versions/hashes, and snapshot/policy/semantic
versions. Unknown fields, including rows, row counts, summaries, and computed
measures, are rejected. Limits are 4,000 question characters, 32,768 SQL UTF-8
bytes, 100 filters/metrics, and 200 objects/labels, with lower configured question
and SQL budgets honored. Total encoded context JSON must fit both the configured
request byte budget and input-context budget. The existing context estimator
counts UTF-8 bytes as tokens. Identifier sizes are 255 characters; label names
are 200 characters and descriptions 2,000 characters.

`BoundParameter` declares an immutable named, explicitly typed driver scalar
(string, integer, finite float, boolean, date, datetime, or finite Decimal).
JSON roundtrips retain date/datetime/Decimal types using the scalar type tag.
`ResolvedParameters` declares up to 100 bindings, copied recursively immutable
supplied values, optional inclusive-start/exclusive-end date boundaries, and an
effective `max_rows` (default 100, hard maximum 1,000). Empty bindings/values are
valid. These are declarations only; compilation, capability fingerprints, and
driver execution are implemented by Task 6.

`QueryRunRepository.complete(query_id, context, canonical_sql, assumptions,
warnings, truncated)` writes all context, version, SQL, explanation metadata,
and `status="completed"` in one SQL UPDATE guarded against every terminal state.
A successful update increments `state_version` once; a missing or terminal run
returns false with no metadata changes. The enclosing transaction commits or
rolls back that entire update. Callers remain responsible for current ownership,
catalog/policy authorization, and cache publication. `update_state` continues to
serve existing stages/errors and legacy callers.

Existing rows default to natural-language origin with nullable context/version
fields. Existing completed SQL remains readable. Migration never infers an author
limit, original template, metric use, or semantic provenance. Legacy runs without
context/versions are ineligible as follow-up parents until rerun; eligibility is
enforced when follow-up execution is introduced.

## C09 — History, retention, and deletion

History repository listings remain owner-scoped with stable keyset pagination.
They include origin, parent/source IDs, and saved-question ID/revision. Listings
exclude submitted SQL, accepted definition snapshots, and run context/parameter
payloads. Public responses include typed origin and relationship/revision fields.

Deleting or expiring a run removes its run-local context/accepted parameter data
and cascades attempts; cached rows are evicted. Removing an ancestor clears
parent/source pointers while retaining the child's independent context and audit
metadata. Retention never deletes saved definitions, parameter defaults, or
choices merely because their original runs expired. Deleting a saved definition
retains historical saved IDs/revisions and accepted definition snapshots until
those runs themselves are removed. Source rows remain volatile, never persisted
in context, definitions, or history.

## Task 1 verification — 2026-11-08

The initial repository/migration test run failed on the missing
`querylens.domain.analytics` interface (exit 2), before authentication or source
credentials were involved. After implementation, the focused repository and real
migration tests passed from both the API directory and repository root.

Final commands used the installed `.venv` environment:

- From `apps/api`: `python -m pytest tests/unit tests/integration tests/security -q -ra`
  — exit 0, 173 passed, 3 skipped. The skips are existing live PostgreSQL/MySQL
  source execution and PostgreSQL vertical-slice tests without source credentials.
- From repository root: `ruff check apps/api` — exit 0.
- From `apps/api`: `mypy --config-file mypy.ini src` — exit 0, 86 source files.

The new PostgreSQL migration gate did not skip. It initialized disposable local
PostgreSQL 16 clusters without application credentials, upgraded through 0002,
seeded a legacy completed run, upgraded to head, compared metadata including
server defaults, inspected named constraints and partial indexes, downgraded to
0002, and re-upgraded. Behavioral deletion, retention, label uniqueness, and
origin-constraint tests ran against both PostgreSQL and FK-enabled SQLite.
This verifies metadata persistence; it does not claim new source-driver behavior
or PostgreSQL 17/18 or MySQL source compatibility.


## C05 — Authorized catalog labels and semantic snapshots

Physical `CatalogSnapshot.snapshot_hash` and `policy_version` retain their existing
meaning. Labels and metric edits do not change physical identifiers, types, hashes,
or policy versions. The connection's monotonic `semantic_version` advances in the
same transaction as a successful label replacement or changed metric definition,
enabled state, or deletion. Metric PATCH requests that make no change retain both
versions. Label replacements advance the semantic version even when their visible
contents are unchanged; individual unchanged label versions remain stable.

`GET /api/v1/connections/{connection_id}/labels` returns
`{semantic_version, labels}`. Each label contains the exact physical `namespace`,
`table_name`, optional `column_name`, `display_name`, optional `description`, and
`version`. `PUT` accepts `{expected_semantic_version, labels}` and replaces only
currently visible labels. Inputs omit server-owned versions. Names are nonempty
and at most 200 characters, descriptions at most 2,000, identifiers at most 255,
and replacements at most 200 entries, subject to the existing request byte limit.
MySQL labels use their actual database namespace, without a `public` fallback.

Table display names are unique within a namespace. Column display names are
unique within their physical table, in a separate scope from table display names.
Alias comparisons use Unicode NFKC, collapsed whitespace, and casefold; physical
identifiers keep their engine-sensitive spelling. Duplicate targets or normalized
display names return 409. Targets outside the current visible catalog return 422.
Hidden label records survive visible replacements, cannot be republished by a
client, and never appear in GET responses or generation context. Hidden records
also reserve their display names in their scope, with generic conflict messages.

Semantic writes lock the owner-scoped connection row, check the latest physical
snapshot and policy, validate definitions and expected versions, and commit all
metadata/version changes atomically. Stale versions or a catalog changed between
loading and locking return 409 without partial writes. Unknown and foreign
connection IDs return the same 404. Mutations retain session-bound CSRF and
approved-origin verification. Semantic reads use a shared connection lock for a
consistent metadata/version view.

`load_semantic_context(user_id, snapshot)` returns `SemanticContext` containing
that version, visible label copies, and enabled metrics validated against the
current catalog. Generation loads this owner-authorized context explicitly.
Ranker/context functions accept an optional semantic context compatibly; labels,
metric names/keys/descriptions, and configured synonyms contribute to retrieval.
Selected metric tables are included ahead of other ranked tables. Prompts contain
complete structured metric DSL (including filters, grain, units, description, and
synonyms) and labeled physical targets. Complete selected metric definitions and
their table schemas must fit the existing byte-based context budget; otherwise
context construction fails rather than silently dropping metric semantics.
Optional examples remain bounded and SQL-validated.

## C10 — Versioned metric editing and alias conflicts

`MetricDSL.synonyms` defaults to `[]` for legacy stored DSL. It accepts at most 20
non-whitespace strings, each at most 100 characters. Metric names remain at most
200 characters and descriptions at most 1,000. Canonical hashes include synonyms
and are deterministic across JSON reloads. Table/measure/filter/grain references
must resolve to visible physical objects; qualified column references must belong
to the metric's own table. Alias normalization never rewrites these identifiers.

Existing metric POST/GET/DELETE routes remain. POST checks normalized keys,
names, and synonyms against every enabled definition, including hidden records,
without identifying conflicting definitions in errors. A conflict returns 409.
Disabling a metric removes its aliases from this conflict set; re-enabling checks
again. Exact metric keys retain their existing connection-wide database uniqueness
constraint, including disabled definitions. GET filters invalid or hidden targets
while retaining visible disabled metrics for editing. DELETE is owner-scoped,
including definitions whose targets are no longer visible, and advances the
semantic version only after an actual deletion.

`PATCH /api/v1/connections/{connection_id}/metrics/{metric_id}` accepts
`{expected_version, dsl?, enabled?}` with at least one non-null change. `dsl` is the
complete replacement structured definition. A changed DSL or enabled state
increments the metric version once and advances the connection semantic version
once. A stale metric version returns 409; missing, foreign, and hidden PATCH
targets return 404. The returned metric includes its complete DSL and new version.

## Task 2 verification — 2026-11-08

The initial semantic tests failed on missing semantic interfaces (exit 2). Focused
coverage now verifies synonym-only retrieval, complete DSL and labels in the
actual provider prompt, normalized conflicts, disabled aliases, exact physical
references, hidden/revoked metadata, legacy loading, payload bounds, CSRF/ownership,
optimistic versions, and MySQL database namespaces. Disposable PostgreSQL tests
synchronize competing writers and verify that exactly one label replacement or
conflicting metric creation commits, with a single semantic version increment.

Validation uses the installed `.venv` environment, with backend commands run from
`apps/api` as specified by the plan. Final verification:

- `python -m pytest tests/unit tests/integration tests/security -q -ra`: 186 passed, 3 skipped.
- `ruff check apps/api`: passed.
- `mypy --config-file apps/api/mypy.ini apps/api/src`: passed (89 source files).
- `npm run typecheck --prefix apps/web`: passed.
- Exported OpenAPI equals the runtime schema, including both label methods and metric PATCH.

The existing three live-source execution/vertical-slice tests skip without source
credentials. Disposable PostgreSQL concurrency and migration gates do not skip.
A separate repository-root run loaded the local `.env` and failed live-source TLS
certificate checks plus the existing vertical-slice admission setup; it is not
source-engine compatibility evidence. No source-driver behavior is changed here.
OpenAPI is re-exported, corresponding semantic TypeScript contracts are updated,
and Ruff, Mypy, and frontend TypeScript checks pass.

## C01/C06 — Authenticated manual SQL and validated provenance

`POST /api/v1/queries/sql` is an authenticated, owner-scoped read-only SQL
endpoint. It accepts `connection_id`, `sql`, optional `source_query_id`, and
`max_rows` (default 100, hard maximum 1,000). The approved-origin and session-bound
CSRF rules apply. This explicitly permits authenticated manual SQL submission;
it does not add unauthenticated SQL access or relax source network restrictions,
engine allowlists, function restrictions, visible-catalog authorization, or
read-only transactions.

An optional source must be an owner-authorized completed run on the same
connection. Unknown and foreign sources return 404; incomplete or mismatched
sources return 422 before admission. The worker checks source eligibility again.
The accepted response remains `{query_id, status:"queued"}` with HTTP 202.
Configured SQL UTF-8 byte and row budgets apply before acceptance and again in
the worker. Unsafe statements, multiple statements, unresolved placeholders,
hidden identifiers, locking reads, and forbidden functions become terminal
rejected runs without source dispatch. Direct execution never invokes generation
or repair, even after syntax or database errors.

`validate_query_artifact` produces an internal `ValidatedArtifact` containing the
executable token, authorized canonical template before fetch-limit injection,
original top-level author limit, and empty resolved bindings with the effective
row budget. The compatibility wrapper `validate_and_bound_sql` still returns a
`ValidatedQuery`. Without an author LIMIT, request 100 executes with LIMIT 101
while storing `author_limit=null`; explicit LIMIT 20 remains 20. Submitted SQL is
retained separately from bounded canonical executed SQL. Manual runs use origin
`manual_sql` and neutral meaning; the original question cannot confer business
meaning on an edited query. Direct attempts retain zero prompt/completion tokens.

## C07/C08 — Shared execution lifecycle

Natural-language and manual runs use `run_with_lifecycle`, which owns admission
activation, total deadline, safe terminal errors, cancellation, cleanup, and task
deregistration. `RunServices.execute` uses the existing bounded DBAPI executor,
remaining statement/connect/cleanup budgets, source cancellation, and socket
termination fallback. A cancelled asyncio waiter does not release its active
lease while its DBAPI worker is still running. Shutdown/startup reconciliation
continues to mark unfinished prior runs interrupted.

Publication locks the owner-scoped connection and checks the latest physical
snapshot, policy version, and semantic version in the transaction that atomically
completes durable run metadata. Drift prevents publication. Cancellation and
other terminal states cannot be overwritten; a lost completion race evicts any
cached rows. Rows and result-derived presentation are never persisted.

## Task 3 — Structured schema editing

The schema explorer shows editable business labels alongside inspectable physical
namespace/table/column names. Label saves use PUT with the loaded semantic version;
metric edits PATCH the complete structured DSL and expected metric version.
The editor supports descriptions, synonyms, units, all six aggregations, grain,
and all existing filter operators with scalar/list types. Server conflicts and
validation errors preserve drafts. Connection changes invalidate stale reads and
save callbacks, including catalog and metric-list requests. All client mutations
use the shared credentials, client-header, and CSRF path.

## C08/C09 — Verified intent and volatile answer presentation (Task 4)

`build_run_context(template_sql, author_limit, question, origin, snapshot,
semantics, resolved_parameters=None)` resolves physical objects and column types
from the authorized template AST, including nested scopes and expanded stars.
Supported conjunctive literal predicates become typed audit filters. Unsupported
predicates remain inspectable in the authoritative canonical SQL template.
Effective descriptions use verified physical scope; arbitrary question wording
never proves business meaning. Manual SQL always uses a neutral description.

A metric reference requires one plain single-table SELECT with exactly one
supported aggregation and matching measure, group columns, and complete filter
set. Joins, derived scopes, OR, windows, HAVING, extra projections, and other
unsupported shapes receive no metric claim. Numeric filters compare exact
context-independent decimal representations, preserving long integers and
negative values; string and boolean literals remain distinct. Enabled metric
IDs, versions, and DSL hashes are retained, alongside copies of labels on the
referenced objects. No result rows or computed summaries enter stored context.

Completed GET responses explicitly map origin, parent/source IDs, saved-question
ID/revision, and optional authorized context. Historical label copies are filtered
against current physical visibility. Metric references and display definitions
require a currently enabled, visible, identical version/hash; removing a reference
also removes the effective description's stale verified-metric claim. Legacy
runs may omit context and presentation.

`PresentationMetadata` is a typed volatile contract with title, deterministic
explanation, chart type (`table`, `single_value`, `line`, `bar`), optional x/y
columns and exact single value, at most 50 plotting row indices, typed date scope,
currently verified metric display definitions/units, and visible warnings.
Definitions include ID, key, version, name, description, and declared units.
Unknown units are absent. Conflicting declared units fall back to a table.
Explanations never call a model or persist with query history.

Single values require exactly one non-null numeric cell and preserve its exact
string, including integers beyond the JavaScript safe range. Plotting requires
exactly two compatible columns, 1..50 rows, unique nonempty valid keys, and no
null measures. Numeric-looking columns declared as strings are ineligible.
Plot values must be finite and their shortest JavaScript-number-compatible
decimal representation must equal the original exact decimal value; integral
values outside ±9,007,199,254,740,991 are ineligible. Distinct exact values may
never collapse to one plotted number. Date keys must be valid; equivalent
timestamp instants are duplicate keys. Temporal recommendations provide sorted
row indices without changing table order. Unsupported shapes use the complete
table, with no sampling or aggregation. Truncation warnings remain explicit.

`ResultCache.get_entry` retains the original monotonic expiry and byte eviction
rules; cache TTL is capped at 300 seconds. `results_expires_at` translates the
remaining TTL to UTC without refreshing it. GET derives presentation only from
an owner-authorized entry matching the current physical/policy snapshot. Expiry,
eviction, missing snapshots, and stale policy omit rows, presentation, and expiry
and return `results_available:false`. Reading completed results never reflects
or connects to a source to repair stale authorization metadata. CSV uses the
same current snapshot/policy check and returns 410 when unavailable. Public
history maps origins and relationship/revision metadata while excluding rows.

Task 4 validation on 2026-11-08: the initial scoped run failed during collection
on the missing intent module. The final installed-environment command
`python -m pytest tests/unit/test_presentation_and_charts.py tests/integration/test_presentation_delivery.py tests/integration/test_history.py tests/unit/test_csv_export.py -q`
passed 40 tests, including authenticated GET/history, hidden metadata,
foreign ownership, policy revocation without source reflection, TTL/eviction,
and CSV 410. Scoped Ruff and mypy checks also pass. Source-engine execution is
unchanged by this presentation task and is not claimed by these checks.

Physical-table aliases may rename the table, but may not supply positional column
alias lists. Catalog visibility can omit source columns, so their positional
mapping cannot be safely inferred. Derived-table and CTE aliases retain existing
scoped validation. Unsupported table modifiers (including TABLESAMPLE and ONLY)
do not prove a full-table metric definition and receive neutral presentation.
The metric editor selects actual physical measure columns and rejects numeric
scalar/list input whose JSON number representation would change its exact decimal
value. It preserves the entered draft so the author can revise it explicitly.

## Tasks 2–5 final verification — 2026-11-08

All commands used the installed environment. Backend tests ran from `apps/api`
so the repository-root `.env` could not select external source credentials.

- `python -m pytest tests/unit tests/integration tests/security -q -ra`:
  exit 0, 254 passed, 3 skipped. The skips remain existing live PostgreSQL,
  MySQL, and PostgreSQL vertical-slice cases without configured credentials.
  Disposable PostgreSQL migration/concurrency tests passed without skipping.
- `npm test --prefix apps/web`: exit 0, 49 tests passed across 7 files.
- `ruff check apps/api`: exit 0.
- `mypy --config-file apps/api/mypy.ini apps/api/src`: exit 0, 94 source files.
- Frontend lint, TypeScript checking, and production build: exit 0.
- Deterministic exported OpenAPI bytes match the runtime schema. Explicit
  TypeScript declarations include origin/lineage, run context, presentation,
  manual SQL requests, and history. The exporter emits JSON, not TypeScript.

New tests were first observed red for absent label UI, presentation interfaces,
and manual endpoint/lifecycle behavior. Independent reviews prompted fixes for
unsupported wildcard metric measures, exact scalar/list numeric entry, and
unsupported table modifiers/positional column aliases; their focused regressions
passed and review confirmed the fixes. An early combined test process imported
an old repair fixture while it was being corrected; the final whole backend run
uses a computed snapshot hash and passes the existing repair assertions.
No PostgreSQL/MySQL source-driver changes are claimed, and the skipped external
source tests are not source-engine compatibility evidence. Backend presentation
recommendations and the manual endpoint are delivered here; chart rendering and
workspace SQL editing remain their later plan tasks.

The final integration review also verified metric conflict recovery: an explicit
Cancel discards the draft and reloads current definitions before reopening; the
next PATCH uses the new server version. The complete web suite passes after this
fix, and the scoped final review reports no remaining findings.

## C06 — Parameter Slots, Immutable Capability Tokens, and Driver Bindings (Task 6)

`BoundParameter(name, scalar_type, value)` and `ResolvedParameters` provide immutable
typed driver bindings. Capability tokens (`ValidatedQuery`) carry an immutable tuple
of `bindings: tuple[BoundParameter, ...] = ()`. A deterministic typed fingerprint
function `compute_token_fingerprint` hashes the canonical SQL, bindings, connection ID,
engine, policy version, snapshot hash, permitted identifiers, and effective max rows
deterministically using SHA-256. `SafeExecutor.execute` checks this fingerprint before
credential access, and revalidates the canonical AST (prohibited constructs, function
policy, and placeholder-binding set equality) before source dispatch.

`compile_driver_statement(sql: str, engine: str, bindings: tuple[BoundParameter, ...])`
in `sql/bindings.py` renders named placeholders as DBAPI pyformat `%(name)s` for both
PostgreSQL (`psycopg`) and MySQL (`PyMySQL`). Literal `%` characters not belonging to a
valid parameter token are escaped to `%%`. This compilation is applied after metadata
probe (`metadata_probe_sql`) and oversize-guard (`bounded_source_sql`) transformations,
passing bound parameters to both cursor executions.

`extract_eligible_parameters` and `compile_parameterized_query` in `sql/parameters.py`
offer only unambiguous conjunctive WHERE predicates and server-owned result count.
Date range presets (`this_month`, `this_year`, `fixed`) resolve to UTC inclusive starts
and exclusive midnight ends. Category parameters enforce type-aware membership against
allowed scalars. Result counts are clamped by author LIMIT and system limits. Values
are strictly bound through driver parameters and never interpolated into SQL text.

## Task 6 verification — 2026-11-08

Backend tests ran from `apps/api`:
- `python -m pytest tests/unit/test_sql_parameters.py tests/integration/test_parameter_execution.py -q`: 11 passed.
- `python -m pytest tests/unit tests/integration tests/security -q -ra`: 265 passed, 3 skipped.
- `ruff check apps/api`: exit 0.
- `mypy --config-file apps/api/mypy.ini apps/api/src`: exit 0, 96 source files.

