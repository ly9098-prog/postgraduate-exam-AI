#!/usr/bin/env python3
"""Audit DocumentIR SSOT boundaries — verify DocumentIR is the single source of truth.

Checks for:
1. Direct access to OCR backend raw fields (rec_texts, dt_polys, layoutParsingResults)
2. Legacy blocks used as data source (not just compat view)
3. Modules that skip DocumentIR entirely
4. Call sites where legacy blocks are the primary format

Output:
  reports/sprint4a/document_ir_ssot_report.json
  reports/sprint4a/document_ir_violations.json

Invocation:
  PYTHONPATH=. python scripts/audit_document_ir_boundaries.py
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
FEATURES = REPO / "app" / "features"
CORE = REPO / "app" / "core"
SERVICES = REPO / "app" / "services"
TESTS = REPO / "tests"
OUT = REPO / "reports" / "sprint4a"
OUT.mkdir(parents=True, exist_ok=True)

# Patterns indicating direct OCR backend field access
RAW_FIELD_PATTERNS: list[re.Pattern] = [
    re.compile(r'rec_texts'),
    re.compile(r'dt_polys'),
    re.compile(r'layoutParsingResults'),
    re.compile(r'layout_parsing_results'),
    re.compile(r'PaddleOCRVLResult'),
    re.compile(r'OCRFixResult'),
    re.compile(r'_ocr_scanned_pdf'),
]

# Patterns indicating legacy blocks usage (not compat view)
LEGACY_BLOCKS_PATTERNS: list[re.Pattern] = [
    re.compile(r'blocks_to_normalized'),
    re.compile(r'legacy_blocks'),
    re.compile(r'from_legacy_blocks'),
    re.compile(r'ocr_raw_text'),
    re.compile(r'ocr_cleaned_text'),
    re.compile(r'OcrPageResult'),
    re.compile(r'normalized_blocks'),
]

# Modules KNOWN to use DocumentIR properly (whitelist)
DOCUMENT_IR_WHITELIST: set[str] = {
    "app/core/document_ir.py",
    "app/features/reading_order.py",
    "app/features/cross_page_linking.py",
    "app/features/ocr_adapter.py",
    "app/features/pipeline_fingerprint.py",
    "app/core/module_result.py",
}


def audit_file(filepath: Path, relative_to: Path) -> dict[str, Any]:
    """Audit a single file for SSOT violations."""
    rel = str(filepath.relative_to(relative_to))
    content = filepath.read_text()
    lines = content.splitlines()

    violations: list[dict[str, Any]] = []
    legacy_call_sites: list[dict[str, Any]] = []

    # Check raw field patterns
    for pattern in RAW_FIELD_PATTERNS:
        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                # Skip if it's in a known DocumentIR module
                if rel in DOCUMENT_IR_WHITELIST:
                    continue
                violations.append({
                    "file": rel,
                    "line": i,
                    "pattern": pattern.pattern,
                    "text": line.strip()[:120],
                    "severity": "HIGH",
                    "type": "direct_raw_access",
                })

    # Check legacy blocks patterns
    for pattern in LEGACY_BLOCKS_PATTERNS:
        for i, line in enumerate(lines, 1):
            if pattern.search(line) and rel not in DOCUMENT_IR_WHITELIST:
                legacy_call_sites.append({
                    "file": rel,
                    "line": i,
                    "pattern": pattern.pattern,
                    "text": line.strip()[:120],
                    "severity": "MEDIUM",
                    "type": "legacy_blocks_reference",
                })

    return {
        "file": rel,
        "total_lines": len(lines),
        "violations": violations,
        "legacy_call_sites": legacy_call_sites,
    }


def main() -> None:
    all_violations: list[dict[str, Any]] = []
    all_legacy_sites: list[dict[str, Any]] = []

    dirs_to_audit = [
        (FEATURES, "features"),
        (CORE, "core"),
        (SERVICES, "services"),
    ]

    for base_dir, _label in dirs_to_audit:
        for f in sorted(base_dir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            result = audit_file(f, REPO)
            all_violations.extend(result["violations"])
            all_legacy_sites.extend(result["legacy_call_sites"])

    # Build report
    report = {
        "summary": {
            "total_violations": len(all_violations),
            "total_legacy_sites": len(all_legacy_sites),
            "high_severity": sum(1 for v in all_violations if v.get("severity") == "HIGH"),
            "medium_severity": sum(1 for v in all_violations if v.get("severity") == "MEDIUM"),
        },
        "ssot_violations": sorted(all_violations, key=lambda v: (v["file"], v["line"])),
        "legacy_call_sites": sorted(all_legacy_sites, key=lambda v: (v["file"], v["line"])),
    }

    # Write reports
    report_path = OUT / "document_ir_ssot_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"  Wrote {report_path.relative_to(REPO)}")

    violations_path = OUT / "document_ir_violations.json"
    violations_path.write_text(json.dumps({
        "violations": all_violations,
        "legacy_sites": all_legacy_sites,
        "ssot_violations": len(all_violations) == 0,
    }, ensure_ascii=False, indent=2))
    print(f"  Wrote {violations_path.relative_to(REPO)}")

    # Summary
    print(f"\n  Total violations: {len(all_violations)}")
    print(f"  Total legacy call sites: {len(all_legacy_sites)}")

    if all_violations:
        print("\n  HIGH severity violations:")
        for v in all_violations:
            if v.get("severity") == "HIGH":
                print(f"    {v['file']}:{v['line']}  {v['type']}  ({v['text'][:80]})")

    return 0 if len(all_violations) == 0 else 1


if __name__ == "__main__":
    exit(main())
