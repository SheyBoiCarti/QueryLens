# Configuration and deployment

[Back to the README](README.md)

Run the API from the repository root so it loads `.env`. Source connection passwords are entered through the app and saved encrypted in the metadata database; they do not belong in `.env`.

## Settings

| Setting | Purpose | Default / requirement |
|---|---|---|
| `ENVIRONMENT` | Runtime profile | `development`; use `production` for deployment |
| `LLM_PROVIDER` | Natural-language query provider | Unset; `openai`, `groq`, `openrouter`, or `live` |
| `LLM_MODEL` | Provider model identifier | Required for natural-language queries |
| `LLM_API_KEY` | Provider credential | Set for hosted providers |
| `LLM_API_BASE` | Override the OpenAI-compatible endpoint | Provider preset when omitted; configure for a custom endpoint |
| `METADATA_DATABASE_URL` | Stores connections, schema metadata, metrics, saved questions, and history | `sqlite+pysqlite:///./metadata.db` in development; PostgreSQL required in production |
| `CREDENTIAL_KEYS_FILE` | Path to a JSON credential encryption keyring | Set to the generated file in the quickstart; required in production |
| `CREDENTIAL_ACTIVE_KEY_ID` | Key ID used for new credential encryption | `local` for the quickstart keyring; required in production |
| `SOURCE_PERMITTED_CIDRS` | Optional allowlist for source destination IPs | JSON array, e.g. `["10.20.0.0/16"]`; private source networks require explicit permission in production |
| `ALLOWED_ORIGINS` | Allowed browser origins | Localhost port 5173 in development; explicit HTTPS origins required in production |

Restart the API after changing settings. See [config.py](apps/api/src/querylens/config.py) for all settings and bounds.

Keep the metadata database and keyring together in backups. Losing a key prevents decryption of passwords encrypted with it. The keyring format is `{"keys": {"key-id": "<64 hexadecimal characters>"}}`, where each key decodes to 32 bytes. The quickstart generates a random key instead of relying on the built-in development fallback.

## Sample PostgreSQL database

This optional example requires Docker Engine or Docker Desktop with Docker Compose. It starts only a source database; keep the API and frontend running as described in the README. Run these commands from the repository root.

```bash
docker compose -f infra/compose.yaml up -d --wait postgres-fixture
docker compose -f infra/compose.yaml exec postgres-fixture psql -U querylens_admin -d analytics_pg
```

At the `psql` prompt, paste the following SQL. It creates a small sample table in the fixture database; use a fresh fixture without an existing `orders` table.

```sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    order_date DATE NOT NULL,
    status TEXT NOT NULL,
    total_amount NUMERIC(12, 2) NOT NULL
);

INSERT INTO orders VALUES
    (1, '2024-01-10', 'completed', 120.00),
    (2, '2024-01-20', 'completed', 80.00),
    (3, '2024-02-05', 'completed', 300.00),
    (4, '2024-02-15', 'cancelled', 50.00);

GRANT SELECT ON orders TO analyst_read;
```

Enter `\q` to exit. In QueryLens **Connections**, add:

| Field | Value |
|---|---|
| Engine | PostgreSQL |
| Host | `127.0.0.1` |
| Port | `5433` |
| Database | `analytics_pg` |
| Username | `analyst_read` |
| Password | `analyst_secret_123` |
| TLS | Disabled for this local fixture |

The credentials above are public fixture credentials, for local development only. After importing the schema, make `orders` and its columns visible. Ask **“Show total revenue from completed orders by month in 2024.”** The expected totals are **200.00 for January** and **300.00 for February**. You can also use manual SQL:

```sql
SELECT EXTRACT(MONTH FROM order_date) AS month,
       SUM(total_amount) AS revenue
FROM orders
WHERE status = 'completed'
GROUP BY EXTRACT(MONTH FROM order_date)
ORDER BY month;
```

Stop the fixture with `docker compose -f infra/compose.yaml stop postgres-fixture`. Its named volume preserves the data. The larger [benchmark datasets](datasets/) are separate from this example; `scripts/seed.ps1` currently calls a placeholder command and does not load them.

## PostgreSQL metadata in development

SQLite is sufficient for the local quickstart. To use the development Compose metadata database instead:

```bash
docker compose -f infra/compose.yaml up -d --wait metadata-db
```

Set the following in `.env`, then restart the API:

```dotenv
METADATA_DATABASE_URL=postgresql+psycopg://querylens_meta:meta_dev_password_only@127.0.0.1:5432/querylens_metadata
```

Changing the URL selects a different metadata database; it does not transfer existing connections or history. Development startup applies migrations to the selected database.

## Deployment

The [production Compose configuration](infra/compose.prod.yaml) includes Caddy, an API container, a migration service, and PostgreSQL metadata storage. It requires:

- `QUERYLENS_DOMAIN`: the DNS hostname used for HTTPS and browser origins.
- `METADATA_DB_PASSWORD`: a unique metadata database password.
- `METADATA_DATABASE_URL`: the PostgreSQL SQLAlchemy URL pointing to `metadata-db:5432/querylens_prod`, using user `querylens_app` and the URL-encoded password.
- `CREDENTIAL_KEYS_FILE`: the host path to a provisioned keyring file, readable by the API container user (UID 1000).
- `CREDENTIAL_ACTIVE_KEY_ID`: an ID present in that keyring.
- LLM settings for natural-language queries and `SOURCE_PERMITTED_CIDRS` when accessing private source networks.

The production file sets the HTTPS origin and runs migrations before API startup. It mounts the keyring at `/run/secrets/keyring.json`. Use one API process per metadata database because active jobs and cached results belong to that process.

**The production profile does not add authentication.** Restrict access to trusted users through your deployment's access controls. Preserve both metadata and encryption keys when backing up an instance.

## Troubleshooting

| Symptom | Check |
|---|---|
| App page does not load | Start the frontend separately; `scripts/dev.ps1` launches only the API. |
| API cannot be reached from the app | Confirm the API is listening on `127.0.0.1:8000`; Vite proxies `/api` there. |
| Natural-language questions are unavailable | Fill in the LLM provider, model, and API key in `.env`, then restart the API. |
| Saving a connection fails with an encryption error | Configure the generated 32-byte keyring and active key ID from the quickstart. |
| Database connection fails | Check host, port, credentials, TLS settings, and permitted source networks. The local fixture has TLS disabled. |
| PowerShell cannot activate the virtual environment | Use `.\.venv\Scripts\python.exe` instead of `python` for the Windows Python commands; activation is optional. |
