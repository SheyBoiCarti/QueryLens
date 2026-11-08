# Code review hardening implementation plan

> Execute inline on local branch `fix/code-review-hardening`. The user authorized all review fixes and prohibited running tests. Do not run test suites or disguised behavioral tests. Verify with syntax, type, lint, build, configuration inspection, and a final source audit. Do not push or deploy.

**Goal:** Address all 13 review findings and the architecture/code-quality recommendations without discarding existing functionality.

**Architecture:** Keep FastAPI, SQLGlot, SQLAlchemy and React. Resolve SQL through SQLGlot scopes against qualified authorized metadata; bind catalog/cache/execution to connection policy. Keep volatile jobs in a deliberately enforced single-process runtime with bounded admission and source cancellation, while using durable sessions and CSRF derivation. Integrate the existing semantic and retrieval layers.

**Review focus:** CTE/alias scope escapes; qualified stars and duplicate result names; cancellation during connection/statement execution; changing connection policy during generation; failed polling and expired sessions.

- [x] Create local branch and inspect current state; preserve existing work.
- [x] 1. SQL authorization: schema/database identity, scoped columns, correlated subqueries, CTEs, qualified stars and aliases. Inspect SQLGlot APIs; add focused regression coverage without running it.
- [x] 2. Policy lifecycle: invalidate snapshots/results on connection changes, guard stale execution, validate history/export cache access, and preserve result metadata and unique output columns.
- [x] 3. Source connectivity: verify TLS identity and custom CAs, retain destination pinning, apply operator network policy and bounded driver timeouts.
- [x] 4. Job runtime: bounded active/waiting admission, worker execution, source cancellation, exception-safe lease release, deadline budgets, startup reconciliation, retention, shutdown, and real readiness.
- [x] 5. Authentication/configuration: reachable login, session/CSRF restoration, durable token derivation, consistent production validation and settings; explicit single-worker ownership.
- [x] 6. Analytics: integrate ranked schema, safe verified examples and metric definitions, bounded prompts/output, fan-out warnings, persisted assumptions/warnings.
- [x] 7. Frontend: table/column discovery and connection editing, typed query state, resilient polling/retry, history inspection, expired results and errors.
- [x] 8. Deployment: built frontend image, provisioned keyring, migration command/service, production origin settings, health and deployment documentation.
- [x] 9. Code quality and verification: restore meaningful lint/type checks, synchronize contracts, run non-test checks with compact logs, inspect all requirement paths, reconcile this checklist.

## Rulings and evidence

- User's explicit no-tests instruction overrides skill TDD/test gates. Added regression coverage will remain unexecuted and final reporting must say so.
- User requested a local branch; use this checkout rather than introducing another worktree. Baseline was clean when branch was created.
- Keep volatile result storage; enforce one API process rather than introduce persistent result storage or silently claim multi-worker support.
- No dependency installs, deployments, external database changes, or pushes are needed to begin repairs.

## Completion evidence

All review findings are mapped to implementation and verification in `docs/REVIEW-FIXES.md`. Final backend lint/type checks and frontend lint/strict type checks/production build passed. Source, migration and regression syntax and deployment YAML parsed successfully. No tests or live/deployment probes ran. Docker is unavailable. The repository branch was changed externally during work; the requested local fix branch was recreated without discarding edits. No push or deployment was performed.
