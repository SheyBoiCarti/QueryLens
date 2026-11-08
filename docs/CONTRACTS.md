# Analytics contracts

This document records persistence and semantic metadata delivered by Everyday
Analytics Tasks 1 and 2. Answer presentation, parameter compilation, and new
execution origins are owned by subsequent tasks in the implementation plan.

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
payloads. Public response additions are introduced by the later delivery task.

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
