"""Characterize security headers, access tracing and middleware ordering."""

import asyncio

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core import http_middleware as middleware
from app.core import log_context
from app.core.http_error_handlers import register_http_exception_handlers


@pytest.fixture(autouse=True)
def clear_context():
    log_context.clear_log_context()
    yield
    log_context.clear_log_context()


def request(headers=(), *, query=b"token=synthetic-private&token=other&page=2"):
    return Request({
        "type": "http", "method": "GET", "path": "/synthetic", "query_string": query,
        "headers": [(name.encode(), value.encode()) for name, value in headers],
        "client": ("192.0.2.1", 1234),
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("path,auth", [
    ("/ordinary", False), ("/api/v1/auth/login", True),
    ("/api/admin/v1/auth/refresh", True), ("/api/v1/authenticate", True),
])
async def test_security_header_defaults_and_auth_prefix(monkeypatch, production, path, auth):
    incoming = Request({"type": "http", "path": path, "headers": [], "method": "GET"})
    response = Response(headers={"X-Frame-Options": "SAMEORIGIN", "Cache-Control": "private"})

    async def downstream(value):
        assert value is incoming
        return response

    actual = await middleware.create_security_headers_middleware(
        production_mode=production,
    )(incoming, downstream)
    assert actual is response
    assert actual.headers["X-Content-Type-Options"] == "nosniff"
    assert actual.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert actual.headers["Referrer-Policy"] == "no-referrer"
    assert actual.headers["Permissions-Policy"] == (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    assert actual.headers.get("Strict-Transport-Security") == (
        "max-age=31536000; includeSubDomains" if production else None
    )
    assert actual.headers["Cache-Control"] == "private"
    assert actual.headers.get("Pragma") == ("no-cache" if auth else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [
    "ok", "exception", "cancelled", "start_log_error", "finish_log_error", "error_log_error",
])
async def test_access_logging_order_safe_metadata_and_cleanup(monkeypatch, outcome):
    events = []
    ticks = iter([100.0, 100.125, 100.25])
    monkeypatch.setattr(middleware.time, "time", lambda: next(ticks))

    def capture(logger, event, **fields):
        events.append((logger.name, event, fields, dict(log_context.get_log_context())))
        if (outcome, event) in {
            ("start_log_error", "http.request.start"),
            ("finish_log_error", "http.request.finish"),
            ("error_log_error", "http.request.error"),
        }:
            raise RuntimeError("synthetic log failure")

    monkeypatch.setattr(log_context, "log_event", capture)
    response = JSONResponse({"status": "ok"}, headers={"X-Request-ID": "overridden"})
    failure = asyncio.CancelledError() if outcome == "cancelled" else ValueError("private")

    async def downstream(_incoming):
        assert log_context.get_log_context()["request_id"] == "safe-request"
        if outcome in {"exception", "cancelled", "error_log_error"}:
            raise failure
        return response

    incoming = request([
        ("x-request-id", "safe-request"), ("x-trace-id", "safe-trace"),
        ("authorization", "Bearer synthetic-private"), ("user-agent", "a" * 250),
        ("content-type", "application/json"), ("content-length", "17"),
    ])
    if outcome == "ok":
        result = await middleware.log_requests(incoming, downstream)
        assert result is response
        assert result.headers["X-Request-ID"] == "safe-request"
        assert result.headers["X-Trace-ID"] == "safe-trace"
        assert events[-1][1] == "http.request.finish"
        assert events[-1][2]["duration_ms"] == 125
        assert events[-1][2]["status_code"] == 200
    else:
        expected = RuntimeError if outcome.endswith("_log_error") else type(failure)
        with pytest.raises(expected) as caught:
            await middleware.log_requests(incoming, downstream)
        if not outcome.endswith("_log_error"):
            assert caught.value is failure
        assert events[-1][1] == (
            "http.request.start" if outcome == "cancelled" else "http.request.error"
        )
    assert log_context.get_log_context() == {}
    fields = events[0][2]
    assert fields["query_keys"] == ["token", "page"]
    assert fields["client_ip"] == "192.0.2.1"
    assert fields["user_agent"] == "a" * 200
    assert fields["content_type"] == "application/json"
    assert fields["content_length"] == "17"
    assert "synthetic-private" not in str(events)
    assert all(event[0] == "app.access" for event in events)
    assert all(event[3]["trace_id"] == "safe-trace" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,expected_trace", [
    ([("x-trace-id", "safe-trace")], "safe-trace"),
    ([("traceparent", "00-" + "1" * 32 + "-" + "2" * 16 + "-01")], "tr_" + "1" * 32),
    ([("x-trace-id", "invalid space")], "generated-trace"),
])
async def test_access_correlation_normalizes_or_generates_ids(monkeypatch, headers, expected_trace):
    monkeypatch.setattr(log_context, "generate_trace_id", lambda: "generated-trace")
    monkeypatch.setattr(log_context, "generate_request_id", lambda: "generated-request")
    monkeypatch.setattr(log_context, "log_event", lambda *_args, **_kwargs: None)

    async def downstream(_incoming):
        return Response()

    response = await middleware.log_requests(
        request([*headers, ("x-request-id", "invalid request value")]), downstream,
    )
    assert response.headers["X-Trace-ID"] == expected_trace
    assert response.headers["X-Request-ID"] == "generated-request"
    assert log_context.get_log_context() == {}


@pytest.mark.parametrize("production", [False, True])
def test_real_stack_order_cors_host_and_exception_responses(monkeypatch, production):
    monkeypatch.setattr(log_context, "log_event", lambda *_args, **_kwargs: None)
    app = FastAPI()
    middleware.register_http_middleware(
        app, allowed_hosts=["testserver"], cors_origins=["https://allowed.example"],
        production_mode=production,
    )
    register_http_exception_handlers(app)

    @app.get("/api/v1/auth/synthetic")
    async def endpoint(fail: bool = False):
        if fail:
            raise HTTPException(409, detail="synthetic-private")
        return {"status": "ok"}

    client = TestClient(app)
    headers = {
        "Origin": "https://allowed.example",
        "X-Request-ID": "safe-request", "X-Trace-ID": "safe-trace",
    }
    for path, status in [
        ("/api/v1/auth/synthetic", 200),
        ("/api/v1/auth/synthetic?fail=true", 409),
        ("/api/v1/auth/synthetic?fail=invalid", 422), ("/missing", 404),
    ]:
        response = client.get(path, headers=headers)
        assert response.status_code == status
        assert response.headers["Access-Control-Allow-Origin"] == headers["Origin"]
        assert response.headers["Access-Control-Expose-Headers"] == "X-Request-ID, X-Trace-ID"
        assert response.headers["X-Request-ID"] == "safe-request"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert ("Strict-Transport-Security" in response.headers) is production
        if path.startswith("/api/v1/auth"):
            assert response.headers["Cache-Control"] == "no-store"
        assert "synthetic-private" not in response.text

    rejected = client.get("/api/v1/auth/synthetic", headers={**headers, "Host": "invalid"})
    assert rejected.status_code == 400
    assert rejected.text == "Invalid host header"
    assert rejected.headers["X-Frame-Options"] == "DENY"
    assert rejected.headers["X-Trace-ID"] == "safe-trace"
    preflight = client.options("/api/v1/auth/synthetic", headers={
        **headers, "Access-Control-Request-Method": "GET",
    })
    assert preflight.status_code == 200
    assert preflight.headers["X-Frame-Options"] == "DENY"
    assert preflight.headers["X-Request-ID"] == "safe-request"
    assert preflight.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_query_parse_failure_and_missing_client_keep_start_event(monkeypatch):
    class BrokenQuery(Request):
        @property
        def query_params(self):
            raise ValueError("synthetic malformed query")

    events = []
    monkeypatch.setattr(
        log_context, "log_event",
        lambda _logger, event, **fields: events.append((event, fields)),
    )
    incoming = BrokenQuery({"type": "http", "path": "/", "method": "GET", "headers": []})

    async def downstream(_incoming):
        return Response()

    await middleware.log_requests(incoming, downstream)
    assert events[0][1]["query_keys"] == []
    assert events[0][1]["client_ip"] == "-"
    assert events[0][1]["user_agent"] == "-"
    assert log_context.get_log_context() == {}


@pytest.mark.asyncio
async def test_security_mode_is_owned_by_each_registered_application():
    apps = [FastAPI(), FastAPI()]
    for app, production in zip(apps, [True, False], strict=True):
        middleware.register_http_middleware(
            app, allowed_hosts=["testserver"], cors_origins=[], production_mode=production,
        )

    async def downstream(_incoming):
        return Response()

    incoming = request()
    for app, production in [(apps[0], True), (apps[1], False), (apps[0], True)]:
        dispatch = app.user_middleware[1].kwargs["dispatch"]
        response = await dispatch(incoming, downstream)
        assert ("Strict-Transport-Security" in response.headers) is production
