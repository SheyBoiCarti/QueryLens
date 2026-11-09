"""FastAPI application factory for QueryLens."""

from __future__ import annotations

import asyncio
import uuid
import time
import contextlib
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from querylens.config import Settings, get_settings, set_settings
from querylens.api.health import router as health_router
from querylens.api.auth import router as auth_router
from querylens.api.connections import router as connections_router
from querylens.api.schema import router as schema_router
from querylens.api.history import router as history_router
from querylens.api.queries import router as queries_router
from querylens.api.metrics import router as metrics_router
from querylens.api.labels import router as labels_router
from querylens.api.saved_questions import router as saved_questions_router
from querylens.api.exports import router as exports_router
from querylens.api.errors import register_error_handlers
from querylens.utils.workers import shutdown_db_executor
from querylens.observability.logging import log_event


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager."""
    settings = getattr(app.state, "settings", get_settings())
    log_event("app_startup", stage="startup", status="ok")

    from querylens.connections.keyring import load_keyring
    from querylens.jobs.runtime import RuntimeOwnership
    from querylens.jobs.state import reconcile_interrupted_runs
    from querylens.jobs.runner import graceful_shutdown
    from querylens.persistence.retention import run_retention_cleanup
    from querylens.utils.workers import run_db
    from querylens.api.health import set_runtime_ready

    set_runtime_ready(False)
    from querylens.jobs.admission import initialize_admission_controller

    initialize_admission_controller()
    ownership = RuntimeOwnership()
    load_keyring(settings.credential_keys_file, settings.credential_active_key_id)
    if settings.environment == "production":
        await run_db(ownership.acquire)
    if settings.environment == "development":
        from querylens.persistence.session import get_db_connection
        from querylens.persistence.tables import users, connections
        import sqlalchemy as sa

        # Existing development databases need the same migrations as production.
        from alembic import command
        from alembic.config import Config
        from pathlib import Path
        from querylens.persistence.session import get_engine

        root = Path(__file__).resolve().parents[2]
        migration_config = Config(str(root / "alembic.ini"))
        migration_config.set_main_option("script_location", str(root / "migrations"))
        if (
            "alembic_version" not in sa.inspect(get_engine()).get_table_names()
            and "users" in sa.inspect(get_engine()).get_table_names()
        ):
            command.stamp(migration_config, "0001_initial")
        command.upgrade(migration_config, "head")
        if settings.development_auth_bypass:
            with get_db_connection() as conn:
                dev_user_id = "00000000-0000-0000-0000-000000000000"
                existing = conn.execute(sa.select(users.c.id).where(users.c.id == dev_user_id)).scalar()
                if not existing:
                    conn.execute(
                        users.insert().values(
                            id=dev_user_id,
                            email="admin@querylens.local",
                            password_hash="dev-only-password-hash",
                            role="admin",
                        )
                    )

                # Auto-seed Aiven connections from .env if present
                if settings.postgres_host:
                    pg_conn = conn.execute(
                        sa.select(connections.c.id).where(
                            connections.c.user_id == dev_user_id,
                            connections.c.engine == "postgresql",
                        )
                    ).scalar()
                    if not pg_conn:
                        from querylens.connections.crypto import encrypt_credential

                        conn_id = "pg-aiven-default-conn"
                        enc_pw = encrypt_credential(settings.postgres_password or "", connection_id=conn_id)
                        conn.execute(
                            connections.insert().values(
                                id=conn_id,
                                user_id=dev_user_id,
                                name="Aiven PostgreSQL",
                                engine="postgresql",
                                host=settings.postgres_host,
                                port=int(settings.postgres_port or 5432),
                                database=settings.postgres_db or "defaultdb",
                                username=settings.postgres_user or "avnadmin",
                                encrypted_password=enc_pw,
                                tls_enabled=True,
                                allowed_tables="{}",
                            )
                        )

                if settings.mysql_host:
                    my_conn = conn.execute(
                        sa.select(connections.c.id).where(
                            connections.c.user_id == dev_user_id,
                            connections.c.engine == "mysql",
                        )
                    ).scalar()
                    if not my_conn:
                        from querylens.connections.crypto import encrypt_credential

                        conn_id = "my-aiven-default-conn"
                        enc_pw = encrypt_credential(settings.mysql_password or "", connection_id=conn_id)
                        conn.execute(
                            connections.insert().values(
                                id=conn_id,
                                user_id=dev_user_id,
                                name="Aiven MySQL",
                                engine="mysql",
                                host=settings.mysql_host,
                                port=int(settings.mysql_port or 3306),
                                database=settings.mysql_db or "defaultdb",
                                username=settings.mysql_user or "avnadmin",
                                encrypted_password=enc_pw,
                                tls_enabled=True,
                                allowed_tables="{}",
                            )
                        )

    await run_db(reconcile_interrupted_runs)
    await run_db(run_retention_cleanup, retention_days=settings.retention_days)

    async def maintain() -> None:
        next_retention = time.monotonic() + settings.maintenance_interval_sec
        while True:
            await asyncio.sleep(1)
            try:
                await run_db(ownership.heartbeat)
            except Exception:
                from querylens.jobs.admission import get_admission_controller

                set_runtime_ready(False)
                get_admission_controller().stop()
                log_event("runtime_ownership_lost", status="failed")
                await graceful_shutdown(settings.cleanup_timeout_sec)
                return
            if time.monotonic() >= next_retention:
                try:
                    await run_db(run_retention_cleanup, retention_days=settings.retention_days)
                except Exception:
                    log_event("retention_cleanup_failed", status="failed")
                next_retention = time.monotonic() + settings.maintenance_interval_sec

    set_runtime_ready(True)
    maintenance = asyncio.create_task(maintain())
    try:
        yield
    finally:
        set_runtime_ready(False)
        maintenance.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await maintenance
        await graceful_shutdown(settings.cleanup_timeout_sec)
        await run_db(ownership.release)
        shutdown_db_executor(wait=False)
        log_event("app_shutdown", stage="shutdown", status="ok")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure FastAPI application."""
    if settings is not None:
        set_settings(settings)
    else:
        settings = get_settings()

    settings.validate_for_production()

    app = FastAPI(
        title="QueryLens API",
        version="0.1.0",
        description="Natural-language analytics for PostgreSQL and MySQL",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # CORS configuration
    if settings.environment == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Request ID and size limit middleware
    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        req_id = request.headers.get("x-request-id")
        if not req_id:
            req_id = str(uuid.uuid4())

        content_length = request.headers.get("content-length")
        try:
            declared = int(content_length) if content_length is not None else 0
            if declared < 0:
                raise ValueError()
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "INVALID_CONTENT_LENGTH",
                        "message": "Invalid content length",
                        "request_id": req_id,
                    }
                },
                headers={"Cache-Control": "no-store", "X-Request-ID": req_id},
            )
        too_large = declared > settings.max_request_bytes
        body = bytearray()
        if not too_large:
            async for chunk in request.stream():
                if len(body) + len(chunk) > settings.max_request_bytes:
                    too_large = True
                    break
                body.extend(chunk)
        if too_large:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": "Request exceeds byte budget",
                        "request_id": req_id,
                    }
                },
                headers={"Cache-Control": "no-store", "X-Request-ID": req_id},
            )
        request._body = bytes(body)

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        # C09: Responses carrying credentials, auth tokens, schema, runs or results use Cache-Control: no-store
        response.headers["Cache-Control"] = "no-store"
        return response

    # Register error handlers
    register_error_handlers(app)

    # Mount routers under /api/v1
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(connections_router, prefix="/api/v1")
    app.include_router(schema_router, prefix="/api/v1")
    app.include_router(history_router, prefix="/api/v1")
    app.include_router(queries_router, prefix="/api/v1")
    app.include_router(exports_router, prefix="/api/v1")
    app.include_router(metrics_router, prefix="/api/v1")
    app.include_router(labels_router, prefix="/api/v1")
    app.include_router(saved_questions_router, prefix="/api/v1")
    # Also mount health at root /health for simple container probes
    app.include_router(health_router, prefix="")

    return app


app = create_app()
