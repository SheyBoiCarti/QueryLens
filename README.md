# QueryLens

[![Release Gate](https://github.com/querylens/querylens/actions/workflows/release.yml/badge.svg)](.github/workflows/release.yml)
[![Security Scans](https://github.com/querylens/querylens/actions/workflows/security.yml/badge.svg)](.github/workflows/security.yml)
[![Benchmark Evaluation](https://github.com/querylens/querylens/actions/workflows/evaluation.yml/badge.svg)](.github/workflows/evaluation.yml)

QueryLens is an enterprise natural-language analytics engine for **PostgreSQL 16â€“18** and **Oracle MySQL 8.0/8.4**. It translates natural language questions into secure, read-only SQL queries, displays bounded result grids and transparent assumptions, and provides end-to-end diagnostic observability behind strict multi-tenant isolation and security policies.

---

## Key Features

- **Constrained Read-Only AST Policy:** Translates and parses queries via SQLGlot. Strictly prohibits DDL, DML, transaction control, locking reads (`FOR UPDATE`), recursive CTEs, user variables, and filesystem access. Enforces a strict function allowlist and automatic star expansion with limit clamping.
- **Defense-in-Depth Security:** 
  - **AES-256-GCM Envelope Encryption:** Source database credentials encrypted at rest with 96-bit random IVs and connection-bound Additional Authenticated Data (`AAD`).
  - **SSRF Prevention & DNS Pinning:** Remote database host destinations validated against loopback, private RFC 1918, and cloud metadata ranges (`169.254.169.254`). Sockets pin validated IPs at connect time.
  - **Shared Workspace:** Connections, saved questions, and query history are available without signing in.
  - **Session & CSRF Hardening:** `__Host-` prefixed secure cookies, SameSite enforcement, and cryptographic double-submit HMAC tokens for all mutating actions.
- **Self-Correcting Repair Loop:** Deterministic error classification maps syntax, policy, or runtime engine failures into targeted, bounded repair attempts (max 2) with semantic loop detection.
- **Volatile Caching & Safe CSV Export:** Query results cached strictly in volatile memory (300s TTL) with automatic invalidation on schema changes. CSV streaming export neutralizes spreadsheet formula injection (`=`, `+`, `-`, `@`, `\t`, `\r`, `\n`, `|`).
- **Business Labels & Metric Editing:** The schema explorer supports table/column display names and descriptions. The structured metric editor supports synonyms, units, aggregation, filters, and grain, with version checks for concurrent edits.
- **Verified Answer Metadata:** Completed-query responses include authorized SQL context and conservative chart recommendations derived from currently available rows. Exact numeric strings are preserved; expiry or eviction removes rows and result-derived presentation together.
- **Manual SQL API:** Authenticated `POST /api/v1/queries/sql` accepts read-only SQL and an optional completed source run. It shares query admission, policy validation, budgets, cancellation, and completion checks with natural-language execution, without model generation or repair.
- **Benchmark Suite & Evaluation Harness:** 150 held-out evaluation cases across 8 categories with bipartite multiset comparison, exact string/decimal equality (`1.0 == 1.00`), float tolerance matching, and ablation analysis.

---

## Tech Stack

| Layer | Technologies |
|---|---|
| **API Backend** | Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2, SQLGlot, Psycopg 3, PyMySQL, Cryptography, Argon2-cffi |
| **Web Frontend** | React 18, TypeScript, Tailwind CSS, Lucide icons, Vite |
| **Infrastructure & Ingress** | Docker Compose, Caddy 2 (TLS reverse proxy, security headers), Non-Root Containers |
| **Quality & Verification** | Pytest, Vitest, Playwright, Ruff, Mypy, ESLint |

---

## Project Structure

```
.
â”œâ”€â”€ apps/
â”‚   â”œâ”€â”€ api/                      # FastAPI Python backend service
â”‚   â”‚   â”œâ”€â”€ src/querylens/        # Application modules (ast, llm, pipeline, connections, etc.)
â”‚   â”‚   â””â”€â”€ tests/                # Unit, integration, evaluation, and security test suites
â”‚   â””â”€â”€ web/                      # React SPA frontend (TypeScript, Tailwind, Vite)
â”œâ”€â”€ benchmarks/
â”‚   â””â”€â”€ cases/                    # 150 held-out golden benchmark cases (Contract C10)
â”œâ”€â”€ datasets/                     # Deterministic 10-table business models (PostgreSQL & MySQL)
â”œâ”€â”€ docs/                         # Architecture, security model, runbooks, and contracts
â”‚   â”œâ”€â”€ CONTRACTS.md              # Normative implementation contracts (C01â€“C11)
â”‚   â”œâ”€â”€ DESIGN.md                 # System architecture and domain design
â”‚   â”œâ”€â”€ security.md               # 5-boundary threat model and controls
â”‚   â”œâ”€â”€ deployment.md             # Hardened production deployment topology
â”‚   â”œâ”€â”€ operations.md             # Disaster recovery runbooks (RPO/RTO) and key rotation
â”‚   â”œâ”€â”€ evaluation.md             # Benchmark methodology and results
â”‚   â””â”€â”€ limitations.md            # Text-to-SQL scope and dialect boundaries
â”œâ”€â”€ infra/
â”‚   â”œâ”€â”€ compose.yaml              # Local development compose with fixture databases
â”‚   â”œâ”€â”€ compose.prod.yaml         # Hardened production compose (Caddy, non-root API, meta DB)
â”‚   â””â”€â”€ proxy/Caddyfile           # Reverse proxy configuration with TLS and security headers
â””â”€â”€ scripts/                      # PowerShell automation scripts (verify, dev, backup, restore, etc.)
```

---

## Getting Started

### Prerequisites
- **Python 3.12+**
- **Node.js 20+** & **npm 10+**
- **PowerShell 7 (`pwsh`)**
- **Docker Desktop** / Docker Engine

### 1. Bootstrap Local Environment
Clone the repository and run the bootstrap script to create Python virtual environments, install locked dependencies, and initialize the frontend:

```powershell
pwsh scripts/bootstrap.ps1
```

### 2. Start Development Environment
Launch local support services (PostgreSQL metadata database and integration fixtures) and start the backend and frontend dev servers:

```powershell
pwsh scripts/dev.ps1
```
QueryLens opens directly without authentication. All visitors share connections, saved questions, and query history. Existing account resources are moved into the shared workspace at startup.

- **Web UI:** `http://localhost:5173`
- **API Server:** `http://127.0.0.1:8000`
- **API Documentation:** `http://127.0.0.1:8000/docs`

---

## Verification & Quality Gates

QueryLens enforces strictly non-skipping verification gates across all 10 architectural phases:

```powershell
# Run verification for a specific phase (e.g., Phase 09)
pwsh scripts/verify.ps1 -Phase 09

# Run the full end-to-end release gate (Phases 00â€“10)
pwsh scripts/verify.ps1
```

### Running Benchmark Evaluation
Evaluate pipeline accuracy and safety against the 150 held-out benchmark cases:

```powershell
pwsh scripts/evaluate.ps1 -Engine postgres -Provider fake
```

### Application Smoke Test
Verify running service endpoints:

```powershell
pwsh scripts/smoke.ps1 -BaseUrl http://127.0.0.1:8000
```

---

## Production Deployment

QueryLens provides a hardened, private-network deployment topology where only the Caddy reverse proxy publishes external port 443:

```bash
# 1. Set required production environment secrets
export METADATA_DB_PASSWORD="<strong-password>"
export LLM_API_KEY="<production-llm-key>"
export QUERYLENS_DOMAIN="analytics.example.com"
export METADATA_DATABASE_URL="postgresql+psycopg://querylens_app:<URL-encoded-password>@metadata-db:5432/querylens_prod"
export CREDENTIAL_KEYS_FILE="/absolute/path/to/keyring.json"
export CREDENTIAL_ACTIVE_KEY_ID="prod-key-01"

# 2. Launch production stack
docker compose -f infra/compose.prod.yaml up -d --build
```

Provision the keyring and review the single-worker runtime requirements in [the deployment guide](docs/deployment.md). Bootstrap the administrator with `docker compose -f infra/compose.prod.yaml exec api querylens-admin bootstrap`.

For operational runbooks, backup/restore procedures, and key rotation details, see [`docs/operations.md`](docs/operations.md).

---

## License

Proprietary and confidential. All rights reserved.
