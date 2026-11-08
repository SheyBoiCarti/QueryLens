# QueryLens Development Guide

This guide covers developer workflows, contract management, testing, and acceptance gates for QueryLens.

## Environment Setup

### Backend (Python 3.12)
The backend requires an activated virtual environment with Python 3.12:

```bash
# Activate virtual environment
source .venv/bin/activate

# Install backend with development dependencies
pip install -e "apps/api[dev]"
```

### Frontend (Node 20)
The web application uses Node 20 and npm workspaces:

```bash
# Install npm dependencies
npm install

# Run frontend tests
npm test --prefix apps/web

# Run TypeScript typecheck
npm run typecheck --prefix apps/web

# Build frontend assets
npm run build --prefix apps/web
```

## Schema & Contract Parity

QueryLens enforces strict contract parity between the FastAPI backend and TypeScript frontend:

1. **Deterministic OpenAPI Exporter:**
   ```bash
   python scripts/export_schema.py
   ```
   Exports deterministically serialized JSON (`packages/contracts/openapi.json`) without connecting to live database engines.

2. **Schema Drift Verification Gate:**
   ```bash
   python scripts/export_schema.py --check
   ```
   Compares live FastAPI OpenAPI spec against `packages/contracts/openapi.json`. Exits with non-zero if schema drift is detected.

3. **Shared Contract Fixtures:**
   `packages/contracts/fixtures/everyday_analytics.json` contains representative JSON families for queries, execution statuses, parameter definitions, and presentation metadata. Both backend and frontend contract suites validate against this shared fixture:
   - Backend: `apps/api/tests/unit/test_analytics_contracts.py` validates Pydantic models and exact constraints.
   - Frontend: `apps/web/src/__tests__/analytics_contracts.test.ts` validates TypeScript types using `satisfies` and negative type tests.

## Running Tests

### Full Python Test Suite
Run from `apps/api` with the `.venv` activated:
```bash
cd apps/api
source ../../.venv/bin/activate
python -m pytest tests/unit tests/integration tests/security -v
```

### End-to-End Analytics Journeys
```bash
cd apps/api
source ../../.venv/bin/activate
python -m pytest tests/integration/test_everyday_analytics_e2e.py -v
```

### Full Frontend Suite
```bash
npm test --prefix apps/web
npm run typecheck --prefix apps/web
npm run build --prefix apps/web
```

### Verification Gate Script
```powershell
pwsh scripts/verify.ps1
```
