#!/usr/bin/env python3
"""Audit Local Import Path — Map the existing local import call graph.

Output:
  reports/sprint4b/local_import_call_graph.json
  reports/sprint4b/cloud_api_call_graph.json
"""

from __future__ import annotations

import ast
import json
import os
from collections import defaultdict

REPORTS_DIR = "reports/sprint4b"
os.makedirs(REPORTS_DIR, exist_ok=True)


def extract_calls(filepath: str) -> list[dict]:
    """Extract function calls and imports from a Python file."""
    calls = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            tree = ast.parse(f.read())
    except (SyntaxError, OSError):
        return calls

    for node in ast.walk(tree):
        # Detect function calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                calls.append({
                    "call": f"{ast.unparse(node.func)}()",
                    "line": node.lineno,
                })
            elif isinstance(node.func, ast.Name):
                calls.append({
                    "call": f"{node.func.id}()",
                    "line": node.lineno,
                })
    return calls


# Key features that differentiate profiles
LOCAL_ONLY_FEATURES = {
    "PaddleOCRLocalAdapter", "PaddleOCR", "ocr_model", "OCRFixRouter",
    "page_classifier", "code_detector", "vision_fallback", "ai_repair",
    "question_splitter", "similarity_matcher", "structure_analyzer",
    "ImportTextNormalizer", "safety_check",
}

REMOTE_ONLY_FEATURES = {
    "PaddleOCRVLDocumentAdapter", "OCRGateway", "recognize_page",
}

SHARED_FEATURES = {
    "InputGateway", "InputSafetyValidator", "NativeTextProbe",
    "PageStream", "PageRenderer",
    "ReadingOrderCoordinator", "DomainParsingCoordinator",
    "DocumentStructureCoordinator", "UnifiedSafetyEvaluator",
    "DocumentValidator", "ReviewCoordinator",
    "PipelineExecutionContext", "ExecutionQuota",
    "TraceCollector", "ModuleResult",
}


def main():
    local_graph = []
    cloud_graph = []

    for root, dirs, files in os.walk("app"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.relpath(os.path.join(root, fname))
            calls = extract_calls(fpath)

            entry = {
                "file": fpath,
                "calls": calls,
                "local_only": any(f in str(calls) for f in LOCAL_ONLY_FEATURES),
                "remote_only": any(f in str(calls) for f in REMOTE_ONLY_FEATURES),
                "shared": any(f in str(calls) for f in SHARED_FEATURES),
            }
            if entry["local_only"] or entry["shared"]:
                local_graph.append(entry)
            if entry["remote_only"] or entry["shared"]:
                cloud_graph.append(entry)

    # Write local import call graph
    local_out = os.path.join(REPORTS_DIR, "local_import_call_graph.json")
    with open(local_out, "w") as f:
        json.dump({
            "files": local_graph,
            "file_count": len(local_graph),
            "local_only_features": sorted(LOCAL_ONLY_FEATURES),
        }, f, indent=2, ensure_ascii=False)
    print(f"Wrote {local_out}")

    # Write cloud API call graph
    cloud_out = os.path.join(REPORTS_DIR, "cloud_api_call_graph.json")
    with open(cloud_out, "w") as f:
        json.dump({
            "files": cloud_graph,
            "file_count": len(cloud_graph),
            "remote_only_features": sorted(REMOTE_ONLY_FEATURES),
        }, f, indent=2, ensure_ascii=False)
    print(f"Wrote {cloud_out}")

    print(f"\nLocal import files: {len(local_graph)}")
    print(f"Cloud API files: {len(cloud_graph)}")


if __name__ == "__main__":
    main()
