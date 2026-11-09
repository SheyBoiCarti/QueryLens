# Contributing

Issues and pull requests are welcome. Explain the problem, describe the resulting behavior, and include the checks you ran. Avoid posting credentials or sensitive database details in public issues.

Start with the [README quickstart](README.md#quickstart). Run the commands below from the repository root with the Python virtual environment active.

## Checks

Frontend lint, types, and tests:

```bash
npm run lint --workspace=apps/web
npm run typecheck --workspace=apps/web
npm run test --workspace=apps/web
```

Install the Python development tools, then run unit and SQL security tests:

```bash
python -m pip install -e 'apps/api[dev]'
python -m pytest apps/api/tests/unit apps/api/tests/security
```

Integration tests live in `apps/api/tests/integration/`. Some need PostgreSQL and MySQL fixture databases; inspect the test fixtures and [CI configuration](.github/workflows/ci.yml) for their environment requirements. Browser tests use Playwright and are configured in [playwright.config.ts](playwright.config.ts).

The full release verification script and benchmark wrapper require PowerShell 7 and a Unix-style `.venv/bin/` environment:

```powershell
pwsh scripts/verify.ps1 -Phase 10
pwsh scripts/evaluate.ps1 -Engine postgres -Provider fake
```

The release gate requires configured source databases for its source journeys. The fake provider makes benchmark evaluation deterministic without a hosted LLM key; it is a test provider, not an app setting.

## Repository layout

```text
apps/api/        FastAPI backend, SQL policy, database adapters, migrations, tests
apps/web/        React and TypeScript frontend
benchmarks/      Evaluation and security benchmark cases
datasets/        Deterministic PostgreSQL and MySQL benchmark schemas and generator
infra/           Docker Compose, Caddy, container definitions, database initialization
packages/        Shared API contract artifacts
scripts/         Bootstrap, verification, evaluation, and operations scripts
screenshots/     README screenshots using synthetic data
```

The API uses SQLAlchemy, Pydantic, and SQLGlot. The frontend uses Vite and Tailwind CSS. Quality checks include Pytest, Vitest, Playwright, Ruff, Mypy, and ESLint; see the [GitHub Actions workflows](.github/workflows/) for the configured gates.
