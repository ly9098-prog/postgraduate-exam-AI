"""API Router integrity tests.

Covers:
1. No duplicate method+path routes
2. No legacy/import review/AI import paths in OpenAPI
3. Admin paths use /api/admin/v1
4. Cross-import check: API layer does not import business functions from other API modules
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_no_duplicate_method_path():
    """不存在重复 method + path。"""
    seen = {}
    for route in app.routes:
        methods = getattr(route, "methods", set())
        path = getattr(route, "path", None)
        if methods and path:
            for method in methods:
                if method in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                    key = (method, path)
                    assert key not in seen, f"Duplicate route: {method} {path}"
                    seen[key] = route


def test_no_legacy_routes_in_openapi():
    """OpenAPI 中不包含已下线的废弃接口。"""
    schema = client.get("/openapi.json").json()
    paths = schema["paths"].keys()

    legacy_patterns = [
        "/api/v1/import/upload",
        "/api/v1/import/image/upload",
        "/api/v1/import/review/publish",
        "/api/v1/import/review/approve-and-publish",
        "/api/v1/import/questions/{question_id}/fix",
        "/api/v1/import/submit-review",
        "/api/v1/import/review-queue",
        "/api/v1/ai-import/enrich/{import_id}",
        "/api/v1/ai-import/enrich-batch/{batch_id}",
        "/api/v1/ai-import/complete/{import_id}",
    ]
    for pattern in legacy_patterns:
        assert pattern not in paths, f"Legacy route {pattern} found in OpenAPI"


def test_admin_prefix_uniform():
    """所有 Admin API 路径统一使用 /api/admin/v1。"""
    for route in app.routes:
        path = getattr(route, "path", "") or ""
        if "/admin/" in path:
            assert path.startswith("/api/admin/v1/"), f"Non-standard admin prefix: {path}"


def test_no_cross_import_between_api_modules():
    """API Router 文件之间不得互相 import 业务函数。

    Admin Router 不得从 App Router import 业务函数。
    允许跨 import 的场景仅限聚合 Router 文件（router.py）。
    允许的 import 目标: app.services, app.features, app.schemas, app.models, app.core
    """
    import ast
    import os

    api_dir = os.path.join(os.path.dirname(__file__), "..", "app", "api")
    api_dir = os.path.normpath(api_dir)

    violations = []

    for root, _dirs, files in os.walk(api_dir):
        for fname in files:
            if not fname.endswith(".py") or fname == "__init__.py":
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, api_dir)

            # Skip aggregation router files
            if rel_path in ("router.py", "v1/router.py", "admin/router.py"):
                continue
            # Skip the existing admin.py namespace package
            if fname == "admin.py" and rel_path.startswith("v1"):
                continue

            with open(fpath) as f:
                try:
                    tree = ast.parse(f.read(), filename=fpath)
                except SyntaxError:
                    continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module.startswith("app.api."):
                        for alias in node.names:
                            violations.append(
                                f"{fpath}: imports '{module}.{alias.name}'"
                            )

    for v in violations:
        print(f"CROSS-IMPORT: {v}")
    assert not violations, f"Found {len(violations)} cross-import violation(s)"
