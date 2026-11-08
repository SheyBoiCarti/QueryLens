# Code review remediation

Local branch: `fix/code-review-hardening`.

The user requested fixes for all 13 review findings and the architecture/code-quality recommendations, with no tests run. Changes preserve the Python/FastAPI/SQLAlchemy/SQLGlot and React/TypeScript stack.

| Finding | Implementation evidence |
| --- | --- |
| 1. Physical schema/database authorization | `sql/identifiers.py` validates scoped physical sources by namespace and exact table identity before qualification. Cross-catalog sources are rejected. |
| 2. Column/CTE/star escapes | SQLGlot scope-aware qualification uses only authorized columns, expands qualified/unqualified projection stars, validates correlated scopes, and rejects unresolved stars and whole-row composites. Qualified UDF calls and user-defined cast types are rejected. |
| 3. Stale policies/results | Connection edits increment a durable policy revision and remove old snapshots in the same transaction. Results are evicted by connection. Execution holds a shared metadata row lock, checks current revision/hash, and result delivery/history/export validate current snapshots. |
| 4. TLS identity | PostgreSQL uses `verify-full` with original host and pinned address. MySQL uses an actual SSLContext, original hostname/SNI and a validated preconnected socket; refuses missing TLS capability before authentication. Custom CAs propagate through pooling and controls. |
| 5. Blocking execution/cancellation | Source and metadata work are moved off the event loop. Handles retain the original connection/peer identity and stay registered through rollback. Cancellation uses a separate source control path, bounded graceful cleanup, then direct socket interruption; admission remains held until the worker actually finishes. |
| 6. Admission | Reservations bound queued tasks before scheduling. Activation enforces global/user/source limits; errors, early cancellation, and completion release reservations idempotently. Settings enforce the documented hard bounds. |
| 7. Authentication | App restores `/auth/me` and CSRF before authenticated views, renders login, handles session expiry, and exposes logout. CSRF is deterministically session-bound across restarts. Development bypass is explicit and disabled by default. |
| 8. Connection setup | Creation opens table/column discovery and explicit selection. Existing connections can be edited; omitted passwords/CAs are retained. Empty selections disable analytics. |
| 9. Deployment | Frontend assets are built into Caddy; secrets reference a provisioned file; migration service completes before API startup; origin/domain variables are required; non-root identity and read-only API filesystem are explicit. `.dockerignore` excludes local dependencies/secrets. |
| 10. Lifecycle/readiness | Startup reconciles all nonterminal states, loads keyrings and runs retention. Maintenance repeats cleanup and monitors runtime ownership. Readiness checks metadata plus runtime state; shutdown stops admission, cancels work and disposes pools. |
| 11. Analytics semantics | Ranked schema and namespace-aware join paths, relevant validated metric DSLs and catalog-validated examples feed bounded context. Scoped fan-out analysis yields durable warnings. Assumptions and canonical SQL are retained on query records. |
| 12. Result correctness | Duplicate output labels receive deterministic collision-free names. Sentinel truncation is persisted. Source-side byte guards reject oversized fields before transfer, streaming cursors retain only incrementally budgeted JSON rows, and MySQL packet allocations are capped. |
| 13. Workspace recovery | Sequential abortable polling retries transient errors, exposes manual retry/dismissal, and shows cancellation errors. History passes the selected run ID; completed, expired, interrupted and clarification states are rendered explicitly. |

Architecture/code quality: production enforces one API process per metadata database through a dedicated PostgreSQL advisory lock, rather than silently splitting volatile state across workers. Duplicate production validators are consolidated. Meaningful Python argument/attribute/return checks, unused-import checks, TypeScript unused-symbol checks, and production `any` linting are enabled. OpenAPI now contains discriminated query responses and was regenerated.

## Verification performed

- Backend Ruff lint and Mypy with formerly suppressed call/argument/attribute/return checks enabled.
- Frontend ESLint, strict TypeScript compilation, and production Vite build.
- Python AST syntax inspection of application, migration, and regression sources.
- OpenAPI generation without application lifespan or database connections.
- Production Compose YAML parsing and source inspection of Dockerfiles, Caddy, secrets and migration dependencies.
- Separate read-only backend review; its TLS, cancellation, readiness, duplicate-column and streaming-budget findings were addressed.
- Git whitespace/diff inspection.

No unit, integration, security, evaluation, browser, smoke, or other behavioral tests were run. Regression specifications were added/updated but remain unexecuted. Docker is unavailable in this environment, so images and container startup were not exercised. Live source connectivity, cancellation and model generation remain unverified at runtime under the user's no-tests constraint.

## Operational changes

Apply Alembic revision `0002_review_hardening` before starting the updated production API. Review `docs/deployment.md` for mandatory environment variables, keyring provisioning, administrator bootstrap and the single-worker limit. Development startup migrates existing metadata; the local default user is only seeded when development authentication bypass is explicitly enabled. An older development database containing the placeholder administrator may need `querylens-admin set-password` to establish a valid password.

Source-side guards and streaming reduce result allocation risks; they do not claim to bound arbitrary source-server memory or defend libpq against a malicious/nonconforming server. Keep the source roles restricted, approved data types, egress controls and container memory limits.
