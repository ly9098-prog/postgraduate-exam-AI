#!/usr/bin/env python3
"""Audit Remote OCR Config Resolution — Trace how remote OCR configuration flows from DB to adapters.

Output:
  reports/sprint4d/ocr_config_resolution_map.json
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

REPORTS_DIR = "reports/sprint4d"
os.makedirs(REPORTS_DIR, exist_ok=True)

BACKEND = Path(__file__).resolve().parent.parent / "app"


def trace_config_flow() -> dict:
    """Trace how remote OCR configuration flows through the codebase."""
    findings: dict[str, list[dict]] = {
        "hardcoded_endpoints": [],
        "hardcoded_model_names": [],
        "empty_config_instantiations": [],
        "env_var_config_access": [],
        "db_config_access": [],
        "config_resolvers": [],
    }

    for py_file in sorted(BACKEND.rglob("*.py")):
        try:
            source = py_file.read_text()
        except Exception:
            continue
        rel = str(py_file.relative_to(BACKEND.parent.parent))

        lines = source.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Hardcoded PaddleOCR-VL endpoint
            if "paddleocr.aistudio-app.com" in stripped:
                findings["hardcoded_endpoints"].append({
                    "file": rel,
                    "line": i,
                    "snippet": stripped[:150],
                })

            # Hardcoded model name
            if "PaddleOCR-VL-1.6" in stripped and "import" not in stripped.lower():
                findings["hardcoded_model_names"].append({
                    "file": rel,
                    "line": i,
                    "snippet": stripped[:150],
                })

            # Adapter created with no arguments (empty config)
            if "PaddleOCRVLDocumentAdapter()" in stripped and "import" not in stripped.lower():
                findings["empty_config_instantiations"].append({
                    "file": rel,
                    "line": i,
                    "snippet": stripped[:150],
                })

            # Environment variable config access
            if "os.environ.get" in stripped and any(kw in stripped.lower() for kw in
                                                      ("api", "token", "key", "secret", "endpoint")):
                findings["env_var_config_access"].append({
                    "file": rel,
                    "line": i,
                    "snippet": stripped[:150],
                })

            # DB config resolution via model_config_resolver
            if "resolve_active_model" in stripped or "ensure_db_model_configured" in stripped:
                findings["db_config_access"].append({
                    "file": rel,
                    "line": i,
                    "snippet": stripped[:150],
                })

            # Config resolvers
            if "class.*Resolver" in stripped or "resolve.*config" in stripped.lower():
                if "import" not in stripped.lower():
                    findings["config_resolvers"].append({
                        "file": rel,
                        "line": i,
                        "snippet": stripped[:150],
                    })

    return findings


def main():
    flow = trace_config_flow()
    resolution_map = {
        "config_flow": {
            "ocr_gateway_remote_adapter": (
                "OCRGateway._register_remote_adapter() creates PaddleOCRVLDocumentAdapter() "
                "with NO arguments. The adapter defaults to empty api_token and hardcoded base_url. "
                "This means it will always fail with VL_NOT_CONFIGURED at call time."
            ),
            "ocr_fix_router_config": (
                "OCRFixRouter receives a config dict from pipeline_orchestrator. "
                "The config dict is populated from admin_ai_model_configs table and "
                "admin_ai_configs key-value table. Keys: deepseek_api_key, deepseek_base_url, "
                "paddleocr_vl_api_token, paddleocr_vl_base_url, paddleocr_vl_model."
            ),
            "model_config_resolver": (
                "model_config_resolver.py has resolve_active_model(db, feature) which queries "
                "admin_ai_model_configs by feature capability. Already supports feature-based "
                "model resolution but is NOT wired into OCRGateway."
            ),
            "existing_defaults": (
                "admin_ai_config_service has _DEFAULT_MODELS with a single deepseek-v4-flash entry. "
                "No OCR-specific default model exists in seed data."
            ),
        },
        "capabilities": {
            "ocr_lightweight_capability": "Not explicitly defined in DB. Users can tag models with 'ocr' in features. No lightweight OCR model seeded.",
            "ocr_vl_capability": "Not explicitly defined. PaddleOCR-VL-1.6 would be tagged with 'vision' or 'ocr' in features.",
            "ocr_fix_capability": "Managed via admin_ai_configs key ocr_fix_model. Not a model_config feature tag.",
            "ai_repair_capability": "Managed via admin_ai_configs key completion_auto_*. Not a model_config feature tag.",
        },
        "gaps": [
            "OCRGateway creates remote adapter with empty config — no DB config resolution",
            "No AIModelConfigResolver class — only module-level resolve_active_model function",
            "No config snapshot in PipelineExecutionContext — config not frozen at pipeline start",
            "No OCR_LIGHTWEIGHT / OCR_VL capability distinction in model_config_resolver",
            "OCRFixRouter config dict populated ad-hoc in pipeline_orchestrator, not through unified resolver",
            "No cache for model config queries (admin_ai_configs has TTL cache, but model_configs don't)",
        ],
        "hardcoded_findings": flow,
    }

    out = os.path.join(REPORTS_DIR, "ocr_config_resolution_map.json")
    with open(out, "w") as f:
        json.dump(resolution_map, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")

    print(f"\nHardcoded endpoints: {len(flow['hardcoded_endpoints'])}")
    print(f"Hardcoded model names: {len(flow['hardcoded_model_names'])}")
    print(f"Empty config instantiations: {len(flow['empty_config_instantiations'])}")
    print(f"DB config access sites: {len(flow['db_config_access'])}")


if __name__ == "__main__":
    main()
