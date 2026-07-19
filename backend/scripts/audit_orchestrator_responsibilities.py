#!/usr/bin/env python3
"""Audit Orchestrator Responsibilities — Map what pipeline_orchestrator still does.

Output:
  reports/sprint4c/orchestrator_responsibilities_before.json
  reports/sprint4c/orchestrator_line_count.md
"""

from __future__ import annotations

import ast
import json
import os
import re
from collections import defaultdict

REPORTS_DIR = "reports/sprint4c"
os.makedirs(REPORTS_DIR, exist_ok=True)

ORCHESTRATOR_PATH = "app/features/pipeline_orchestrator.py"

RESPONSIBILITY_PATTERNS = {
    "input_safety": ["safety_check", "InputSafetyValidator", "validate_safety"],
    "page_rendering": ["render_page", "PageRenderer", "pdf_renderer", "render_pdf_page"],
    "ocr_adapter_selection": ["AdapterSelector", "select_ocr", "AdapterRegistry", "backend"],
    "ocr_backend_branching": ["paddleocr", "paddleocr-vl", "backend_name", "backend ==", "rec_texts", "dt_polys"],
    "ocr_raw_field_access": ["rec_texts", "dt_polys", "layoutParsingResults", "OCRFixResult", "normalized_blocks"],
    "document_ir_construction": ["DocumentIR", "PageIR", "document_ir"],
    "reading_order": ["reading_order", "ReadingOrder"],
    "question_splitting": ["split_questions", "question_splitter"],
    "ai_repair": ["ai_repair", "repair_stage", "run_repair_stage"],
    "safety_decision": ["UnifiedSafetyEvaluator", "UnifiedSafetyDecision", "SafetyEvidence"],
    "document_validator": ["DocumentValidator", "DocumentValidationResult"],
    "review_artifact": ["review_artifact", "run_review_stage", "ReviewCoordinator"],
    "persistence": ["question_import_writer", "save_artifact", "persist_"],
    "storage_delete": ["storage", "delete_asset", "asset_outbox"],
    "ocr_gateway_bypass": ["adapter.process", "recognize_page", "ocr_service"],
}


def scan_responsibilities(filepath: str) -> dict[str, list[dict]]:
    """Scan a Python file for responsibility indicators."""
    responsibilities: dict[str, list[dict]] = defaultdict(list)
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        tree = ast.parse(content)
    except (SyntaxError, OSError):
        return responsibilities

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            for resp, patterns in RESPONSIBILITY_PATTERNS.items():
                for pat in patterns:
                    if pat in call_str.lower():
                        responsibilities[resp].append({
                            "line": node.lineno,
                            "call": call_str[:80],
                        })
                        break

    return responsibilities


def count_lines(filepath: str) -> int:
    """Count non-empty, non-comment lines."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return 0
    code_lines = sum(1 for l in lines
                     if l.strip() and not l.strip().startswith("#"))
    total_lines = len(lines)
    return total_lines, code_lines


def main():
    if not os.path.exists(ORCHESTRATOR_PATH):
        print(f"Orchestrator not found at {ORCHESTRATOR_PATH}")
        return

    total_before, code_before = count_lines(ORCHESTRATOR_PATH)
    responsibilities = scan_responsibilities(ORCHESTRATOR_PATH)

    output = {
        "file": ORCHESTRATOR_PATH,
        "total_lines_before": total_before,
        "code_lines_before": code_before,
        "responsibilities": {k: v for k, v in sorted(responsibilities.items())},
        "responsibility_counts": {k: len(v) for k, v in sorted(responsibilities.items())},
    }

    out_path = os.path.join(REPORTS_DIR, "orchestrator_responsibilities_before.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")

    # Line count markdown
    md = f"""# Orchestrator Line Count

Generated: {__import__('datetime').datetime.now().isoformat()}

## Before

| Metric | Value |
|--------|-------|
| File | `{ORCHESTRATOR_PATH}` |
| Total lines | {total_before} |
| Code lines | {code_before} |

## Responsibilities Found

| Responsibility | Call Sites |
|---------------|------------|
"""
    for resp, count in sorted(output["responsibility_counts"].items()):
        md += f"| {resp} | {count} |\n"

    md += "\n## Details\n"
    for resp, sites in sorted(responsibilities.items()):
        if sites:
            md += f"\n### {resp}\n"
            for s in sites[:5]:
                md += f"- Line {s['line']}: `{s['call']}`\n"
            if len(sites) > 5:
                md += f"  ... ({len(sites)} total)\n"

    md_path = os.path.join(REPORTS_DIR, "orchestrator_line_count.md")
    with open(md_path, "w") as f:
        f.write(md)
    print(f"Wrote {md_path}")

    print(f"\nTotal lines: {total_before}, Code lines: {code_before}")
    for resp, count in sorted(output["responsibility_counts"].items()):
        print(f"  {resp}: {count}")
    return output


if __name__ == "__main__":
    main()
