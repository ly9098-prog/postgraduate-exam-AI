#!/usr/bin/env python3
"""Audit Deployment Profiles — Map code to local_import vs cloud_api profile paths.

Output:
  reports/sprint4b/deployment_profile_map.json
"""

from __future__ import annotations

import ast
import json
import os
import sys
from collections import defaultdict

REPORTS_DIR = "reports/sprint4b"
os.makedirs(REPORTS_DIR, exist_ok=True)

APP_DIR = "app"


# High-significance imports to check
IMPORT_PATTERNS = {
    "paddleocr": {"paddleocr", "paddle", "paddleocr.paddleocr", "paddleocr.PaddleOCR"},
    "paddle": {"paddle", "paddle.base", "paddle.framework"},
    "torch_cuda": {"torch.cuda", "torch.backends.cuda"},
    "local_ocr_features": {
        "app.features.ocr_correction",
        "app.features.page_classifier",
        "app.features.code_detector",
        "app.features.vision_fallback",
        "app.features.ai_repair",
    },
    "remote_ocr_features": {
        "app.features.ocr_gateway",
        "app.features.ocr_adapter",
    },
    "shared_features": {
        "app.features.input_gateway",
        "app.features.input_safety",
        "app.features.native_text_probe",
        "app.features.page_stream",
        "app.features.coordinators",
        "app.features.unified_safety",
        "app.features.document_validator",
        "app.core.module_result",
        "app.core.document_ir",
        "app.core.deployment_profile",
    },
    "database_sync": {
        "app.features.sync_merge_service",
        "app.api.v1.sync",
    },
    "batch_import": {
        "app.features.question_splitter",
        "app.features.text_normalizer",
        "app.features.similarity_matcher",
        "app.features.structure_analyzer",
        "app.features.question_type_classifier",
    },
}


def scan_py_file(filepath: str) -> dict:
    """Scan a single Python file for imports matching our patterns."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            return {"imports": {}, "error": "syntax_error"}

    imports = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _categorize_import(filepath, alias.name, imports)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                _categorize_import(filepath, node.module, imports)
                if node.module.startswith("app.features"):
                    for alias in node.names:
                        _categorize_import(filepath, f"{node.module}.{alias.name}", imports)

    return {"imports": dict(imports)}


def _categorize_import(filepath: str, module: str, imports: dict) -> None:
    for category, patterns in IMPORT_PATTERNS.items():
        for p in patterns:
            if module.startswith(p) or module == p:
                imports.setdefault(category, []).append({
                    "file": os.path.relpath(filepath, APP_DIR),
                    "module": module,
                })
                break


def main():
    results = {
        "paddleocr": [],
        "paddle": [],
        "torch_cuda": [],
        "local_ocr_features": [],
        "remote_ocr_features": [],
        "shared_features": [],
        "database_sync": [],
        "batch_import": [],
    }

    for root, dirs, files in os.walk(APP_DIR):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            scan = scan_py_file(fpath)
            for cat, entries in scan["imports"].items():
                if cat in results:
                    results[cat].extend(entries)

    # Determine accessibility per profile
    profile_map = {
        "local_import": {
            "allowed": [
                "paddleocr", "paddle", "torch_cuda",
                "local_ocr_features", "remote_ocr_features",
                "shared_features", "database_sync", "batch_import",
            ],
            "prohibited": [],
        },
        "cloud_api": {
            "allowed": [
                "remote_ocr_features", "shared_features",
            ],
            "prohibited": [
                "paddleocr", "paddle", "torch_cuda",
                "local_ocr_features", "database_sync", "batch_import",
            ],
        },
    }

    output = {
        "import_analysis": results,
        "profile_map": profile_map,
        "paddleocr_in_codebase": len(results.get("paddleocr", [])) > 0,
        "paddleocr_in_codebase_detail": "PaddleOCR code exists in repo but must be profile-guarded",
        "import_summary": {k: len(v) for k, v in results.items()},
    }

    out_path = os.path.join(REPORTS_DIR, "deployment_profile_map.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")
    for cat, entries in results.items():
        print(f"  {cat}: {len(entries)}")

    return output


if __name__ == "__main__":
    main()
