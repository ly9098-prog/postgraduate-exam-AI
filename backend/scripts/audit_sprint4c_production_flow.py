#!/usr/bin/env python3
"""Audit Sprint 4C Production Flow — Map current production import pipeline.

Output:
  reports/sprint4c/production_flow_before.json
"""

from __future__ import annotations

import ast
import json
import os
import re
from collections import defaultdict

REPORTS_DIR = "reports/sprint4c"
os.makedirs(REPORTS_DIR, exist_ok=True)

# Known entry points
ENTRY_POINTS = {
    "public_import": {"app/api/v1/imports.py", "app/api/v1/ai_import.py"},
    "admin_import": {"app/api/v1/admin_imports.py"},
    "import_pipeline_service": {"app/services/import_pipeline_service.py"},
}

_ENTRY_FILES = set()
for files in ENTRY_POINTS.values():
    _ENTRY_FILES.update(files)


def trace_calls(filepath: str, depth: int = 0) -> list[dict]:
    """Extract calls that look like import pipeline invocation."""
    if depth > 3:
        return []
    calls = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return calls

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            # Look for pipeline-related calls
            if call_str and any(kw in call_str.lower() for kw in
                                ["pipeline", "orchestrator", "coordinator", "import", "ocr"]):
                calls.append({
                    "file": filepath,
                    "call": call_str,
                    "line": node.lineno,
                })
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.module and any(kw in node.module.lower() for kw in
                                       ["pipeline", "orchestrator", "coordinator"]):
                    calls.append({
                        "file": filepath,
                        "import": f"from {node.module} import {alias.name}",
                        "line": node.lineno,
                    })

    return calls


def main():
    flow = {
        "entry_points": {
            "public_import_api": "app/api/v1/imports.py",
            "admin_import_api": "app/api/v1/admin_imports.py",
            "import_pipeline_service": "app/services/import_pipeline_service.py",
        },
        "app_router_includes": [],
        "api_endpoint_calls": [],
        "orchestrator_is_main_entry": False,
        "coordinator_pipeline_called_from_production": False,
    }

    # Check router.py for which endpoints include what
    router_path = "app/api/v1/router.py"
    if os.path.exists(router_path):
        with open(router_path) as f:
            content = f.read()
        # Find include_router calls
        for match in re.finditer(r'include_router\((\w+)', content):
            flow["app_router_includes"].append(match.group(1))

    # Check import API endpoints
    for ep_path in _ENTRY_FILES:
        fpath = ep_path
        if os.path.exists(fpath):
            calls = trace_calls(fpath)
            flow.setdefault("api_endpoint_calls", []).extend(calls)

    # Check if pipeline_orchestrator.ImportPipeline is the main entry
    orch_path = "app/features/pipeline_orchestrator.py"
    svc_path = "app/services/import_pipeline_service.py"
    coordinator_path = "app/features/coordinator_orchestrator.py"

    flow["pipeline_orchestrator_exists"] = os.path.exists(orch_path)
    flow["import_pipeline_service_exists"] = os.path.exists(svc_path)
    flow["coordinator_pipeline_exists"] = os.path.exists(coordinator_path)

    # Check import_pipeline_service for orchetrator vs coordinator usage
    if os.path.exists(svc_path):
        with open(svc_path) as f:
            svc_content = f.read()
        flow["import_service_uses_orchestrator"] = "pipeline_orchestrator" in svc_content or "ImportPipeline" in svc_content
        flow["import_service_uses_coordinator"] = "coordinator_orchestrator" in svc_content or "CoordinatorPipeline" in svc_content

    # Check if router directly imports orchestrator
    for fpath in [router_path, "app/main.py"]:
        if os.path.exists(fpath):
            with open(fpath) as f:
                content = f.read()
            if "pipeline_orchestrator" in content:
                flow["direct_orchestrator_import"] = True

    # Count how many stages currently go through coordinator vs orchestrator
    flow["coordinator_pipeline_only_in_tests"] = True
    if os.path.exists(coordinator_path):
        with open(coordinator_path) as f:
            cp_content = f.read()
        # Check if it's imported anywhere in production code
        for root, dirs, files in os.walk("app"):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv")]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                cfpath = os.path.relpath(os.path.join(root, fname))
                if cfpath == coordinator_path:
                    continue
                try:
                    with open(cfpath) as f:
                        if "coordinator_orchestrator" in f.read():
                            flow["coordinator_pipeline_called_from_production"] = True
                            flow["coordinator_production_caller"] = cfpath
                            flow["coordinator_pipeline_only_in_tests"] = False
                except OSError:
                    pass

    out_path = os.path.join(REPORTS_DIR, "production_flow_before.json")
    with open(out_path, "w") as f:
        json.dump(flow, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")
    for k, v in flow.items():
        print(f"  {k}: {v}")

    return flow


if __name__ == "__main__":
    main()
