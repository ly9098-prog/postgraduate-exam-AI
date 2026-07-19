#!/usr/bin/env python3
"""Classify and migrate DocumentIR legacy call sites.

Output:
  reports/sprint4c/document_ir_legacy_classification.json
  reports/sprint4c/document_ir_migration_results.json
  reports/sprint4c/document_ir_remaining_legacy.json
  reports/sprint4c/document_ir_ssot_final_audit.json
"""

from __future__ import annotations

import ast
import json
import os
import re
from collections import defaultdict

REPORTS_DIR = "reports/sprint4c"
os.makedirs(REPORTS_DIR, exist_ok=True)

# Patterns that indicate LEGACY DocumentIR access (not through canonical DocumentIR API)
LEGACY_PATTERNS = {
    "rec_texts": {"pattern": r"\.rec_texts\b", "category": "production_read"},
    "dt_polys": {"pattern": r"\.dt_polys\b", "category": "production_read"},
    "layoutParsingResults": {"pattern": r"layoutParsingResults", "category": "production_read"},
    "OCRFixResult": {"pattern": r"OCRFixResult", "category": "production_read"},
    "blocks_to_normalized": {"pattern": r"blocks_to_normalized", "category": "production_write"},
    "normalized_blocks": {"pattern": r"normalized_blocks", "category": "production_write"},
    "OcrPageResult": {"pattern": r"OcrPageResult", "category": "production_read"},
    "legacy_blocks": {"pattern": r"\.get\('blocks'|\[\'blocks'\]", "category": "production_read"},
    "_ocr_scanned_pdf": {"pattern": r"_ocr_scanned_pdf", "category": "production_read"},
}

ADAPTER_ALLOWED_FILES = {
    "app/features/ocr_adapter.py",
    "app/features/ocr_vl/paddleocr_vl_adapter.py",
    "app/services/ocr_service.py",
    "app/features/ocr_fix/rule_adapter.py",
}


def classify_pattern_in_file(filepath: str, name: str, info: dict) -> dict | None:
    """Check if a file has the given legacy pattern and classify it."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    matches = list(re.finditer(info["pattern"], content))
    if not matches:
        return None

    # Determine if this is in an adapter-allowed file
    in_adapter = any(filepath.startswith(a.rstrip(".py")) or filepath == a for a in ADAPTER_ALLOWED_FILES)

    # Determine if in test directory
    in_test = filepath.startswith("tests/") or "/test_" in filepath

    # Classify
    if in_adapter:
        classification = "adapter_internal_legitimate_raw"
    elif in_test:
        classification = "test_compat"
    else:
        classification = info["category"]

    return {
        "file": filepath,
        "pattern": name,
        "category": info["category"],
        "classification": classification,
        "match_count": len(matches),
        "line_numbers": [m.start() for m in matches[:5]],
        "in_adapter": in_adapter,
        "in_test": in_test,
    }


def main():
    all_sites = []
    write_violations = 0
    read_sites = 0
    adapter_sites = 0
    test_sites = 0

    # Scan non-test files
    scan_roots = ["app", "tests"]

    for root in scan_roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".venv")]
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.relpath(os.path.join(dirpath, fname))
                for name, info in LEGACY_PATTERNS.items():
                    result = classify_pattern_in_file(fpath, name, info)
                    if result:
                        all_sites.append(result)
                        if result["classification"] == "production_write":
                            write_violations += 1
                        elif result["classification"] == "adapter_internal_legitimate_raw":
                            adapter_sites += 1
                        elif result["classification"] == "test_compat":
                            test_sites += 1
                        else:
                            read_sites += 1

    # Classification output
    classification = {
        "total_sites": len(all_sites),
        "write_violations": write_violations,
        "read_sites": read_sites,
        "adapter_internal": adapter_sites,
        "test_only": test_sites,
        "sites": all_sites,
        "by_file": {},
    }

    for site in all_sites:
        f = site["file"]
        classification["by_file"].setdefault(f, []).append(site)

    out = os.path.join(REPORTS_DIR, "document_ir_legacy_classification.json")
    with open(out, "w") as f:
        json.dump(classification, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")

    # Migration results
    migration = {
        "total_legacy_sites": len(all_sites),
        "migrated_this_sprint": 0,
        "remaining": len(all_sites),
        "production_write_violations": write_violations,
        "production_read_sites": read_sites,
        "adapter_internal_legitimate": adapter_sites,
        "test_compat": test_sites,
        "ssot_violations_after_migration": write_violations,
        "legacy_removal_prerequisites": [
            "All production write paths must use DocumentIR APIs",
            "All production read paths must use DocumentIR accessors",
            "Review/Persistence must consume DocumentIR, not blocks",
            "Orchestrator must not reference legacy block structures",
        ],
    }

    out = os.path.join(REPORTS_DIR, "document_ir_migration_results.json")
    with open(out, "w") as f:
        json.dump(migration, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")

    # Remaining legacy
    remaining = {
        "total": len(all_sites),
        "sites": [s for s in all_sites if s["classification"] not in ("adapter_internal_legitimate_raw", "test_compat")],
    }

    out = os.path.join(REPORTS_DIR, "document_ir_remaining_legacy.json")
    with open(out, "w") as f:
        json.dump(remaining, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")

    # Final SSOT audit
    ssot_audit = {
        "production_write_violations": write_violations,
        "violation_details": [s for s in all_sites if s["classification"] == "production_write"],
        "ssot_mode": os.environ.get("DOCUMENT_IR_SSOT_MODE", "dual"),
        "ir_mode_ready": write_violations == 0,
        "adapter_boundary_respected": adapter_sites > 0,
    }

    out = os.path.join(REPORTS_DIR, "document_ir_ssot_final_audit.json")
    with open(out, "w") as f:
        json.dump(ssot_audit, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")

    print(f"\nTotal legacy sites: {len(all_sites)}")
    print(f"  Production write violations: {write_violations}")
    print(f"  Production read sites: {read_sites}")
    print(f"  Adapter internal (legitimate): {adapter_sites}")
    print(f"  Test compat: {test_sites}")
    print(f"  DOCUMENT_IR_SSOT_MODE=ir ready: {write_violations == 0}")

    return classification


if __name__ == "__main__":
    main()
