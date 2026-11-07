"""Standardized API error handling and envelope formatting (Contracts C01, C11)."""

from __future__ import annotations

import uuid
from typing import Any
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from querylens.api.schemas import ErrorDetail, ErrorEnvelope


class AppError(Exception):
    """Base application exception with error code and HTTP status code."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required or invalid session") -> None:
        super().__init__("UNAUTHORIZED", message, status.HTTP_401_UNAUTHORIZED)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Action forbidden") -> None:
        super().__init__("FORBIDDEN", message, status.HTTP_403_FORBIDDEN)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__("NOT_FOUND", message, status.HTTP_404_NOT_FOUND)


class RateLimitError(AppError):
    def __init__(self, retry_after: int = 60, message: str = "Rate limit exceeded") -> None:
        super().__init__("RATE_LIMIT_EXCEEDED", message, status.HTTP_429_TOO_MANY_REQUESTS)
        self.retry_after = retry_after


def make_error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Create standardized JSONResponse error envelope."""
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=request_id,
        )
    )
    resp_headers = {"X-Request-ID": request_id, "Cache-Control": "no-store"}
    if headers:
        resp_headers.update(headers)
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(),
        headers=resp_headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register custom exception handlers on FastAPI application."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        req_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        headers = {}
        if isinstance(exc, RateLimitError):
            headers["Retry-After"] = str(exc.retry_after)
        return make_error_response(exc.status_code, exc.code, exc.message, req_id, headers)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        req_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        code_map = {
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            413: "PAYLOAD_TOO_LARGE",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMIT_EXCEEDED",
        }
        code = code_map.get(exc.status_code, "HTTP_ERROR")
        msg = str(exc.detail) if exc.detail else "An error occurred"
        return make_error_response(exc.status_code, code, msg, req_id)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        req_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        # Sanitize error detail: do not echo input values
        errors_summary = []
        for err in exc.errors():
            loc = " -> ".join(str(l) for l in err.get("loc", []))
            msg = err.get("msg", "Invalid value")
            errors_summary.append(f"{loc}: {msg}")
        message = "; ".join(errors_summary) if errors_summary else "Request validation failed"
        return make_error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_ERROR",
            message,
            req_id,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        req_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        # Do not leak internal exception details
        return make_error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_SERVER_ERROR",
            "An unexpected internal error occurred",
            req_id,
        )
