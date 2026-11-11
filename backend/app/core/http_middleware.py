"""HTTP security and access tracing; application assembly supplies configuration."""

import logging
import time
from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.middleware.base import DispatchFunction, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

import app.core.log_context as log_context


def create_security_headers_middleware(*, production_mode: bool) -> DispatchFunction:
    async def add_security_headers(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        if production_mode:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        if request.url.path.startswith(("/api/v1/auth", "/api/admin/v1/auth")):
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("Pragma", "no-cache")
        return response

    return add_security_headers


def _log_request_start(access_logger: logging.Logger, request: Request) -> None:
    # Extract safe request metadata (no Authorization, no full query values).
    try:
        query_keys = (
            list(request.query_params.keys()) if request.query_params else []
        )
    except Exception:
        query_keys = []
    client_ip = request.client.host if request.client else "-"
    user_agent = request.headers.get("user-agent", "-")[:200]
    content_type = request.headers.get("content-type", "-")
    content_length = request.headers.get("content-length", "-")
    log_context.log_event(
        access_logger,
        "http.request.start",
        method=request.method,
        path=request.url.path,
        query_keys=query_keys,
        client_ip=client_ip,
        user_agent=user_agent,
        content_type=content_type,
        content_length=content_length,
    )


async def log_requests(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    access_logger = logging.getLogger("app.access")
    trace_id = log_context.normalize_trace_id(
        request.headers.get("x-trace-id"),
        request.headers.get("traceparent"),
    )
    request_id = log_context.normalize_request_id(request.headers.get("x-request-id"))
    start = time.time()
    try:
        log_context.bind_log_context(trace_id=trace_id, request_id=request_id)
        _log_request_start(access_logger, request)
        response = await call_next(request)
        elapsed_ms = round((time.time() - start) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        log_context.log_event(
            access_logger,
            "http.request.finish",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=elapsed_ms,
            response_content_length=response.headers.get("content-length", "-"),
        )
        return response
    except Exception as exc:
        elapsed_ms = round((time.time() - start) * 1000)
        log_context.log_event(
            access_logger,
            "http.request.error",
            level="error",
            method=request.method,
            path=request.url.path,
            duration_ms=elapsed_ms,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
        )
        raise
    finally:
        log_context.clear_log_context()


def register_http_middleware(
    app: FastAPI, *, allowed_hosts: Sequence[str], cors_origins: Sequence[str],
    production_mode: bool,
) -> None:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Trace-ID"],
    )
    app.middleware("http")(
        create_security_headers_middleware(production_mode=production_mode)
    )
    app.middleware("http")(log_requests)
