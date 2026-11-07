"""FastAPI application factory for QueryLens."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from querylens.config import Settings, get_settings, set_settings
from querylens.api.health import router as health_router
from querylens.api.auth import router as auth_router
from querylens.api.errors import register_error_handlers
from querylens.utils.workers import shutdown_db_executor
from querylens.observability.logging import log_event


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle manager."""
    settings = getattr(app.state, "settings", get_settings())
    log_event("app_startup", stage="startup", status="ok")
    yield
    # Shutdown logic
    shutdown_db_executor(wait=True)
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
        
        # Check Content-Length bound
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.max_request_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": f"Request body exceeds {settings.max_request_bytes} bytes",
                        "request_id": req_id,
                    }
                },
                headers={"X-Request-ID": req_id},
            )

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
    # Also mount health at root /health for simple container probes
    app.include_router(health_router, prefix="")

    return app


app = create_app()
