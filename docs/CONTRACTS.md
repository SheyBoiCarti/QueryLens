# Persistence contracts

This document records the persistence additions delivered by Everyday Analytics
Task 1. API delivery, semantic editing, parameter compilation, and execution
integration are owned by the subsequent tasks in the implementation plan.

## C04 — Metadata schema and migrations

Production metadata uses PostgreSQL. Alembic revision
`0003_everyday_analytics`, following `0002_review_hardening`, uses explicit DDL
independent of application metadata. SQLAlchemy metadata and migrations declare
matching columns, defaults, constraints, foreign keys, and indexes. SQLite
repository tests enable foreign keys when verifying deletion semantics.

Connections have separate `policy_version` and `semantic_version` integers,
initially 1. Semantic changes will advance the latter; neither historical query
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
