"""Characterize the public HTTP error boundary before moving it out of main."""

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import main
from app.core import http_error_contract as contract
from app.core import http_error_handlers as handlers
from app.core import log_context
from app.core.ai_runtime_guard import AIResourceRejectedError
from app.core.error_codes import ApiError, ErrorCode

STATUS_CODES = {
    503: "QUEUE_UNAVAILABLE DB_UNAVAILABLE STAGING_UNAVAILABLE OCR_PROVIDER_ERROR "
         "AI_PROVIDER_UNAVAILABLE RESOURCE_MEMORY_LOW RESOURCE_DISK_LOW",
    429: "QUEUE_FULL RESOURCE_QUEUE_FULL OCR_RATE_LIMIT AI_RATE_LIMIT AI_OVERLOADED "
         "RESOURCE_DB_POOL_BUSY",
    409: "DB_CONFLICT TASK_FENCING_REJECTED TASK_LEASE_LOST TASK_CANCELLED",
    404: "TASK_NOT_FOUND STAGING_OBJECT_MISSING",
    422: "REVIEW_REQUIRED VALIDATION_ERROR",
    504: "OCR_TIMEOUT AI_TIMEOUT PIPELINE_TIMEOUT",
}


@pytest.fixture(autouse=True)
def clear_context():
    log_context.clear_log_context()
    yield
    log_context.clear_log_context()


def request(headers=()):
    return Request({
        "type": "http", "method": "GET", "path": "/synthetic",
        "headers": [(name.encode(), value.encode()) for name, value in headers],
    })


@pytest.mark.parametrize("code", list(ErrorCode))
def test_api_error_status_for_every_current_enum(code):
    expected = next(
        (status for status, names in STATUS_CODES.items() if code.value in names.split()),
        500,
    )
    assert contract._api_error_status(code) == expected


@pytest.mark.parametrize("detail,expected", [
    ("SYNTHETIC_ERROR", "SYNTHETIC_ERROR"),
    ("ABC", "ABC"),
    ("A" * 64, "A" * 64),
    ("A" * 65, "HTTP_400"),
    ("AB", "HTTP_400"),
    ("unsafe provider message", "HTTP_400"),
    ("lower_case", "HTTP_400"),
    ("A\nSECRET", "HTTP_400"),
    ({"error_code": "TOP_ERROR", "code": "OTHER_ERROR"}, "TOP_ERROR"),
    ({"error_code": "unsafe text", "code": "OTHER_ERROR"}, "HTTP_400"),
    ({"detail": {"code": "NESTED_ERROR"}}, "NESTED_ERROR"),
    ({"detail": {"code": "SECRET /synthetic"}}, "HTTP_400"),
    ({"code": 123}, "HTTP_400"),
    (None, "HTTP_400"),
])
def test_public_code_only_accepts_original_bounded_machine_codes(detail, expected):
    assert contract._extract_public_error_code(detail, 400) == expected


def test_error_content_uses_context_then_headers_and_never_api_error_private_ids():
    incoming = request([("x-request-id", "header-request"), ("x-trace-id", "header-trace")])
    assert contract._request_error_ids(incoming) == ("header-request", "header-trace")
    log_context.bind_log_context(request_id="bound-request", trace_id="bound-trace")
    result = contract._public_error_content(incoming, status_code=503, code="DB_UNAVAILABLE")
    assert result == {"error": {
        "code": "DB_UNAVAILABLE", "message": "服务暂时不可用，请稍后重试",
        "retryable": False, "request_id": "bound-request", "trace_id": "bound-trace",
    }}


def test_context_failure_uses_headers(monkeypatch):
    def fail():
        raise RuntimeError("context unavailable")

    monkeypatch.setattr(log_context, "get_log_context", fail)
    assert contract._request_error_ids(request([("x-request-id", "header-request")])) == (
        "header-request", "",
    )


@pytest.fixture
def error_client():
    app = FastAPI(exception_handlers=dict(main.app.exception_handlers))

    @app.get("/api-error")
    async def api_error():
        raise ApiError(
            ErrorCode.DB_UNAVAILABLE, message="synthetic private database detail",
            details={"query": "synthetic private query"}, request_id="private-id",
            retryable=True,
        )

    @app.get("/http-error")
    async def http_error():
        raise HTTPException(
            409, detail={"error_code": "REVISION_CONFLICT", "private": "synthetic-private"},
            headers={"Retry-After": "7"},
        )

    @app.get("/ai-error/{reason}")
    async def ai_error(reason: str):
        raise AIResourceRejectedError(reason, retry_after_sec=4)

    @app.get("/validate/{number}")
    async def validation(number: int):
        return {"number": number}

    @app.get("/unhandled")
    async def unhandled():
        raise RuntimeError("synthetic-private")

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("path,status,code,retryable", [
    ("/api-error", 503, "DB_UNAVAILABLE", True),
    ("/http-error", 409, "REVISION_CONFLICT", False),
    ("/ai-error/ai_rate_limited", 429, "AI_RATE_LIMIT", True),
    ("/ai-error/ai_overloaded", 429, "AI_OVERLOADED", True),
    ("/ai-error/ai_prompt_too_large", 422, "VALIDATION_ERROR", False),
    ("/ai-error/unknown_reason", 503, "AI_PROVIDER_UNAVAILABLE", True),
    ("/validate/synthetic-private", 422, "VALIDATION_ERROR", False),
    ("/unhandled", 500, "INTERNAL_ERROR", False),
    ("/missing", 404, "HTTP_404", False),
])
def test_registered_handlers_keep_public_envelope(error_client, path, status, code, retryable):
    response = error_client.get(
        path, headers={"X-Request-ID": "synthetic-request", "X-Trace-ID": "synthetic-trace"},
    )
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert error["retryable"] is retryable
    assert error["request_id"] == "synthetic-request"
    assert error["trace_id"] == "synthetic-trace"
    assert "synthetic-private" not in response.text
    assert "private-id" not in response.text
    assert "details" not in error
    if path.startswith("/ai-error"):
        assert response.headers["Retry-After"] == "4"
    if path == "/http-error":
        assert response.headers["Retry-After"] == "7"
    if path == "/unhandled":
        assert response.headers["X-Request-ID"] == "synthetic-request"
        assert response.headers["X-Trace-ID"] == "synthetic-trace"


@pytest.mark.asyncio
@pytest.mark.parametrize("handler,exception,status,code", [
    ("api_error_handler", ApiError(ErrorCode.QUEUE_FULL), 429, "QUEUE_FULL"),
    ("ai_resource_rejected_handler", AIResourceRejectedError("ai_overloaded"), 429, "AI_OVERLOADED"),
    ("http_exception_handler", HTTPException(503, detail="synthetic-private"), 503, "HTTP_503"),
    ("validation_exception_handler", RequestValidationError([]), 422, "VALIDATION_ERROR"),
    ("unhandled_exception_handler", RuntimeError("synthetic-private"), 500, "INTERNAL_ERROR"),
])
async def test_log_sink_failure_does_not_replace_http_response(
    monkeypatch, handler, exception, status, code,
):
    def fail(*_args, **_kwargs):
        raise RuntimeError("log sink unavailable")

    monkeypatch.setattr(log_context, "log_event", fail)
    response = await getattr(handlers, handler)(request(), exception)
    assert response.status_code == status
    assert json.loads(response.body)["error"]["code"] == code


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds,expected", [(None, None), (0, None), (-3, "1"), (2, "2")])
async def test_ai_rejection_retry_after_keeps_existing_truthiness_and_clamp(seconds, expected):
    response = await handlers.ai_resource_rejected_handler(
        request(), AIResourceRejectedError("ai_rate_limited", retry_after_sec=seconds),
    )
    assert response.headers.get("Retry-After") == expected


@pytest.mark.parametrize("status,expected", [
    (200, "请求失败，请稍后重试"),
    (399, "请求失败，请稍后重试"),
    (418, "请求失败，请检查后重试"),
    (499, "请求失败，请检查后重试"),
    (599, "服务暂时不可用，请稍后重试"),
])
def test_unknown_http_status_keeps_original_message_fallback(status, expected):
    assert contract._public_http_message(status) == expected
