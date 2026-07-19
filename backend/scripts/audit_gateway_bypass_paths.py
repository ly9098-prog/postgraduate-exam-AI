#!/usr/bin/env python3
"""Audit Gateway Bypass Paths — Find code that calls OCR without going through OCRGateway.

Output:
  reports/sprint4c/gateway_bypass_paths.json
"""

from __future__ import annotations

import ast
import json
import os
from collections import defaultdict

REPORTS_DIR = "reports/sprint4c"
os.makedirs(REPORTS_DIR, exist_ok=True)

BYPASS_PATTERNS = {
    "direct_adapter_process": {"adapter.process", "adapter.run", ".process("},
    "direct_ocr_service": {"ocr_service.recognize", "ocr_service.run_ocr", "_call_ocr_api"},
    "direct_paddleocr": {"PaddleOCR(", "ocr_model.ocr", "ocr_model("},
    "raw_rec_texts": {"rec_texts", "dt_polys", "layoutParsingResults"},
    "raw_normalized_blocks": {"normalized_blocks", "blocks_to_normalized"},
    "raw_ocr_fix_result": {"OCRFixResult", "OcrPageResult"},
}

# Files that are allowed to bypass (adapter boundary)
ALLOWED_BYPASS_FILES = {
    "app/features/ocr_adapter.py",
    "app/features/ocr_gateway.py",
    "app/services/ocr_service.py",
    "app/ocr_worker/",
}


def scan_bypass_paths() -> dict[str, list[dict]]:
    """Scan all app/ Python files for gateway bypass patterns."""
    bypasses: dict[str, list[dict]] = defaultdict(list)

    for root, dirs, files in os.walk("app"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.relpath(os.path.join(root, fname))

            # Check if file is in allowed bypass zone
            is_allowed = any(fpath.startswith(a) or fpath == a for a in ALLOWED_BYPASS_FILES)

            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
                tree = ast.parse(source)
            except (SyntaxError, OSError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    call_str = (ast.unparse(node.func) if hasattr(ast, "unparse")
                                else "").lower()
                    for pattern_name, patterns in BYPASS_PATTERNS.items():
                        for pat in patterns:
                            if pat.lower() in call_str:
                                bypasses[pattern_name].append({
                                    "file": fpath,
                                    "line": node.lineno,
                                    "call": call_str[:100],
                                    "in_allowed_zone": is_allowed,
                                })
                                break

    return bypasses


def main():
    bypasses = scan_bypass_paths()

    violations = []
    allowed_calls = []

    for pattern_name, sites in bypasses.items():
        for site in sites:
            target = allowed_calls if site["in_allowed_zone"] else violations
            target.append(site)

    output = {
        "total_bypass_sites": len(violations) + len(allowed_calls),
        "violations_outside_adapter_boundary": len(violations),
        "allowed_calls_in_adapter_boundary": len(allowed_calls),
        "violations": violations,
        "allowed_calls": allowed_calls,
        "bypass_pattern_summary": {k: len(v) for k, v in sorted(bypasses.items())},
        "assessment": "",
    }

    if violations:
        output["assessment"] = (
            f"FOUND {len(violations)} gateway bypass sites outside adapter boundary. "
            "These must go through OCRGateway."
        )
    else:
        output["assessment"] = "No gateway bypass violations. All OCR calls go through allowed paths."

    out_path = os.path.join(REPORTS_DIR, "gateway_bypass_paths.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")
    print(f"  Violations: {len(violations)}")
    print(f"  Allowed (adapter boundary): {len(allowed_calls)}")

    for v in violations[:10]:
        print(f"  [VIOLATION] {v['file']}:{v['line']} - {v['call'][:60]}")

    return output


if __name__ == "__main__":
    main()
