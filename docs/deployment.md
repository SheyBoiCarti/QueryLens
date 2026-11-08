# Production deployment

The production stack builds the frontend into Caddy, migrates PostgreSQL metadata before API startup, and mounts an operator-provisioned credential keyring. Only HTTPS port 443 is published. Configure DNS for a hostname you control; Caddy obtains and persists its TLS certificate using TLS-ALPN on port 443.

## Provision configuration

Set these environment variables in the shell or Compose environment file. Do not commit secrets.

- `QUERYLENS_DOMAIN`: public DNS hostname, without scheme or path.
- `METADATA_DB_PASSWORD`: database password for `querylens_app`.
- `METADATA_DATABASE_URL`: `postgresql+psycopg://querylens_app:<URL-encoded-password>@metadata-db:5432/querylens_prod`. The decoded password must match `METADATA_DB_PASSWORD`.
- `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`: supported provider and credentials.
- `CREDENTIAL_KEYS_FILE`: absolute host path to a readable JSON keyring file.
- `CREDENTIAL_ACTIVE_KEY_ID`: a key ID present in that file.
- `SOURCE_PERMITTED_CIDRS`: optional JSON array of explicitly approved source networks, for example `["10.20.0.0/16"]`. Production denies private/reserved sources unless permitted; loopback and metadata/link-local destinations remain prohibited.

Create a keyring outside the repository using a cryptographically random 32-byte key encoded as hex:

```json
{"keys": {"prod-key-01": "<64 hex characters from a secure random generator>"}}
```

Protect and back up the keyring separately from database backups. Ensure container UID 1000 can read the mounted file. A missing file, missing key ID, or malformed key fails startup; production never falls back to the development key.

## Launch

```sh
docker compose -f infra/compose.prod.yaml config --quiet
docker compose -f infra/compose.prod.yaml up -d --build
docker compose -f infra/compose.prod.yaml exec api querylens-admin bootstrap
```

Bootstrap prompts for the initial administrator's email and password. Sign in through the web app, add a database connection with a read-only database account, then select allowed tables and columns. Custom CA certificates are supported in connection settings.

The `migrate` service applies Alembic revisions before API startup. Before an upgrade, back up metadata and keyrings. Recreate the migration service for each release (`docker compose ... up -d --build --force-recreate migrate api`). Existing metadata created outside Alembic must be reviewed and stamped at its actual revision before migrating; do not blindly stamp production databases.

## Runtime ownership and limits

Run exactly one API process/replica per metadata database. A PostgreSQL advisory lock rejects an additional worker at startup. This preserves ownership of volatile results, active jobs, admission and cancellation. Increasing Uvicorn workers or replicating API containers is unsupported until those resources move to a coordinated runtime. Session and CSRF validation survive restarts; source result rows remain memory-only and expire.

Readiness queries the metadata database. Startup marks abandoned nonterminal jobs interrupted. Retention removes expired sessions and query records older than the configured retention period; shutdown stops admission and cancels active work within the cleanup deadline. All source statements also have driver/database timeouts.

The API filesystem is read-only with bounded temporary storage. Named volumes persist PostgreSQL data and Caddy certificate state. Source destinations are validated and pinned at every connection, while TLS verifies the original hostname. Configure egress firewall rules as an additional deployment boundary.
