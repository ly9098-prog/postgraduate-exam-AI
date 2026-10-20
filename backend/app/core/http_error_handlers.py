"""HTTP exception adapters; application assembly owns registration."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.ai_runtime_guard import AIResourceRejectedError
from app.core.error_codes import ApiError, ErrorCode
from app.core.http_error_contract import (
    _api_error_status,
    _extract_public_error_code,
    _public_error_content,
    _request_error_ids,
)

logger = logging.getLogger("postgraduate-ai")


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """Return a stable public error contract; keep backend detail in logs only."""
    status_code = _api_error_status(exc.code)
    try:
        from app.core.log_context import log_event

        log_event(
            logging.getLogger("app.access"),
            "http.api_error",
            level="warning" if status_code < 500 else "error",
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            error_code=exc.code.value,
            backend_message=exc.message,
            backend_details=exc.details,
        )
    except Exception:
        pass
    return JSONResponse(
        status_code=status_code,
        content=_public_error_content(
            request,
            status_code=status_code,
            code=exc.code.value,
            retryable=exc.retryable,
        ),
    )


async def ai_resource_rejected_handler(
    request: Request, exc: AIResourceRejectedError
) -> JSONResponse:
    """Translate AI admission failures into the same safe public error contract."""
    if exc.reason == "ai_rate_limited":
        code = ErrorCode.AI_RATE_LIMIT
        status_code = 429
    elif exc.reason == "ai_overloaded":
        code = ErrorCode.AI_OVERLOADED
        status_code = 429
    elif exc.reason == "ai_prompt_too_large":
        code = ErrorCode.VALIDATION_ERROR
        status_code = 422
    else:
        code = ErrorCode.AI_PROVIDER_UNAVAILABLE
        status_code = 503

    try:
        from app.core.log_context import log_event

        log_event(
            logging.getLogger("app.access"),
            "http.ai_resource_rejected",
            level="warning",
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            error_code=code.value,
            rejection_reason=exc.reason,
            retry_after_sec=exc.retry_after_sec,
        )
    except Exception:
        pass

    headers = {}
    if exc.retry_after_sec:
        headers["Retry-After"] = str(max(1, int(exc.retry_after_sec)))
    return JSONResponse(
        status_code=status_code,
        content=_public_error_content(
            request,
            status_code=status_code,
            code=code.value,
            retryable=status_code in {429, 503},
        ),
        headers=headers,
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Sanitize HTTPException.detail before it crosses the API boundary."""
    code = _extract_public_error_code(exc.detail, exc.status_code)
    try:
        from app.core.log_context import log_event

        log_event(
            logging.getLogger("app.access"),
            "http.expected_error",
            level=(
                "info"
                if exc.status_code == 404
                else "warning"
                if exc.status_code < 500
                else "error"
            ),
            method=request.method,
            path=request.url.path,
            status_code=exc.status_code,
            error_code=code,
        )
    except Exception:
        pass
    return JSONResponse(
        status_code=exc.status_code,
        content=_public_error_content(
            request,
            status_code=exc.status_code,
            code=code,
            retryable=exc.status_code in {429, 502, 503, 504},
        ),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Do not expose Pydantic validation internals or submitted values to clients."""
    try:
        from app.core.log_context import log_event

        log_event(
            logging.getLogger("app.access"),
            "http.validation_error",
            level="warning",
            method=request.method,
            path=request.url.path,
            status_code=422,
            validation_error_count=len(exc.errors()),
        )
    except Exception:
        pass
    return JSONResponse(
        status_code=422,
        content=_public_error_content(
            request,
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR.value,
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # 兜底异常始终返回脱敏 JSON；详细异常只进入后端日志。
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)

    request_id, trace_id = _request_error_ids(request)
    try:
        from app.core.log_context import bind_log_context, log_event

        if trace_id or request_id:
            bind_log_context(trace_id=trace_id, request_id=request_id)
        log_event(
            logging.getLogger("app.access"),
            "http.request.error",
            level="error",
            method=request.method,
            path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
        )
    except Exception:
        pass  # Never let logging crash the exception handler

    response = JSONResponse(
        status_code=500,
        content=_public_error_content(
            request,
            status_code=500,
            code=ErrorCode.INTERNAL_ERROR.value,
        ),
    )
    if trace_id:
        response.headers["X-Trace-ID"] = trace_id
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


def register_http_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(AIResourceRejectedError, ai_resource_rejected_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
