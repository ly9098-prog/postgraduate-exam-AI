"""High-value API contract guardrails.

This deliberately checks only contracts consumed directly by the two frontends.
The generated OpenAPI file covers the full API surface; these assertions make
critical response models mandatory so a route cannot silently fall back to an
untyped ``{}`` schema.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from app.main import app

CRITICAL_OPERATIONS = {
    ("/api/admin/v1/auth/login", "post"): "AdminTokenResponse",
    ("/api/admin/v1/dashboard/overview", "get"): "AdminDashboardOverview",
    ("/api/admin/v1/system/health", "get"): "SystemHealthResponse",
    ("/api/admin/v1/tasks/diagnostics", "get"): "TaskDiagnosticsResponse",
    ("/api/admin/v1/tasks/trace/{trace_id}", "get"): "TaskTraceResponse",
    ("/api/v1/auth/login", "post"): "TokenResponse",
    ("/api/v1/auth/refresh", "post"): "TokenResponse",
    ("/api/v1/practice/questions", "get"): "PracticeQuestionsResponse",
}


def _schema_name(operation: dict) -> str | None:
    responses = operation.get("responses") or {}
    success = responses.get("200") or responses.get("201")
    if not success:
        return None
    content = success.get("content") or {}
    json_content = content.get("application/json") or {}
    schema = json_content.get("schema") or {}
    ref = schema.get("$ref")
    return str(ref).rsplit("/", 1)[-1] if ref else None


def test_critical_frontend_operations_have_typed_success_contracts():
    schema = app.openapi()
    paths = schema["paths"]
    failures: list[str] = []
    for (path, method), expected_schema in CRITICAL_OPERATIONS.items():
        operation = (paths.get(path) or {}).get(method)
        if operation is None:
            failures.append(f"missing {method.upper()} {path}")
            continue
        actual_schema = _schema_name(operation)
        if actual_schema != expected_schema:
            failures.append(
                f"{method.upper()} {path}: expected {expected_schema}, got {actual_schema or 'untyped'}"
            )
    assert not failures, "\n" + "\n".join(failures)


def test_openapi_operation_ids_are_unique():
    schema = app.openapi()
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                continue
            location = f"{method.upper()} {path}"
            previous = seen.setdefault(operation_id, location)
            if previous != location:
                duplicates.append(f"{operation_id}: {previous} / {location}")
    assert not duplicates, "duplicate OpenAPI operationId(s):\n" + "\n".join(duplicates)
