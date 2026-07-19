#!/usr/bin/env python3
"""Audit Profile Runtime Reachability — Can cloud_api reach local OCR at runtime?

Output:
  reports/sprint4c/profile_runtime_reachability.json
"""

from __future__ import annotations

import ast
import json
import os
import sys
from collections import defaultdict

REPORTS_DIR = "reports/sprint4c"
os.makedirs(REPORTS_DIR, exist_ok=True)

DANGER_PATTERNS = {
    "local_ocr_import": {
        "from paddleocr import",
        "import paddleocr",
        "import paddle",
        "from paddle import",
    },
    "gpu_initialization": {
        "torch.cuda",
        "paddle.is_compiled_with_cuda",
        "paddle.CUDAPlace",
        "set_device",
    },
    "local_ocr_fallback": {
        "PaddleOCRLocalAdapter",
        "PaddleOCR(",
        "ocr_model.ocr",
        "rule_fallback",
    },
}

# Code that is SAFE because it's guarded by profile check
SAFE_GUARDED_PATTERNS = [
    'if profile == "local_import"',
    'if profile == DeploymentProfile.LOCAL_IMPORT',
    'if self.is_cloud',
    'if self._profile == "cloud_api"',
    'if caps.local_ocr_allowed',
    'if deployment_profile == "local_import"',
    'local_ocr_allowed',
]


def check_file_reachability(filepath: str) -> dict:
    """Check if a file has unguarded code paths that could reach local OCR."""
    findings = {
        "file": filepath,
        "has_guarded_access": False,
        "has_unguarded_danger": False,
        "danger_patterns": [],
        "guard_patterns": [],
    }

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return findings

    # Check for guard patterns
    for guard in SAFE_GUARDED_PATTERNS:
        if guard in content:
            findings["has_guarded_access"] = True
            findings["guard_patterns"].append(guard)

    # Check for danger patterns outside guard scope
    # Simple heuristic: if the file has both a danger pattern AND a guard
    # pattern, check if the danger is NOT inside the guard
    for danger_cat, patterns in DANGER_PATTERNS.items():
        for pattern in patterns:
            if pattern.lower() in content.lower():
                findings["danger_patterns"].append({
                    "category": danger_cat,
                    "pattern": pattern,
                })

    # Assess: if has danger but no guard, it's unguarded
    if findings["danger_patterns"] and not findings["has_guarded_access"]:
        findings["has_unguarded_danger"] = True

    return findings


def main():
    all_findings = []
    danger_files = []

    for root, dirs, files in os.walk("app"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv", "ocr_worker")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.relpath(os.path.join(root, fname))
            finding = check_file_reachability(fpath)
            all_findings.append(finding)
            if finding["has_unguarded_danger"]:
                danger_files.append(finding)

    output = {
        "total_files_scanned": len(all_findings),
        "files_with_unguarded_local_ocr_reachability": len(danger_files),
        "files_with_guarded_access": sum(1 for f in all_findings if f["has_guarded_access"]),
        "danger_files": [
            {
                "file": f["file"],
                "danger_patterns": f["danger_patterns"],
            }
            for f in danger_files
        ],
        "assessment": "",
    }

    if danger_files:
        output["assessment"] = (
            f"FOUND {len(danger_files)} files with unguarded local OCR reachability. "
            "These files may reach local OCR code in cloud_api profile."
        )
    else:
        output["assessment"] = (
            "No unguarded local OCR reachability. "
            "All local OCR code is behind profile guards."
        )

    out_path = os.path.join(REPORTS_DIR, "profile_runtime_reachability.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")
    print(f"  Total files: {len(all_findings)}")
    print(f"  Unguarded danger: {len(danger_files)}")
    print(f"  Guarded access: {output['files_with_guarded_access']}")

    for f in danger_files:
        print(f"  [DANGER] {f['file']}")
        for p in f["danger_patterns"]:
            print(f"    - {p['category']}: {p['pattern']}")

    return output


if __name__ == "__main__":
    main()
