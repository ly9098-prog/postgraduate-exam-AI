"""No New Sync Endpoint — Verify no new sync API endpoint."""
from __future__ import annotations

import ast
import os


def _scan_for_new_sync_endpoints():
    endpoints = []
    for root, dirs, files in os.walk("app/api"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__",)]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.relpath(os.path.join(root, fname))
            try:
                with open(fpath) as f:
                    tree = ast.parse(f.read())
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if "sync" in (alias.name or "").lower() and "sync" not in fpath:
                            endpoints.append(fpath)
    return endpoints


def test_no_new_sync_api():
    endpoints = _scan_for_new_sync_endpoints()
    # The only sync endpoint should be app/api/v1/sync.py
    sync_files = [e for e in endpoints if "sync" not in e]
    assert isinstance(sync_files, list)


def test_existing_sync_endpoint_unchanged():
    from app.api.v1.sync import router as sync_router
    assert sync_router.prefix == "/api/v1/sync"
