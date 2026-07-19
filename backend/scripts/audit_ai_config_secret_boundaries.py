#!/usr/bin/env python3
"""Audit AI Config Secret Boundaries — Check that secrets never leak into context, artifacts, logs, or error messages.

Output:
  reports/sprint4d/ai_config_secret_audit.json
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

# Patterns that indicate potential secret leakage
LEAK_PATTERNS = [
    ("api_key", "api_key in log/error message"),
    ("api_key_encrypted", "api_key_encrypted in log/error message"),
    ("api_token", "api_token in log/error message"),
    ("decrypt_api_key", "decrypt result used in log/error message"),
    ("secret", "secret in log/error message"),
]

# Files that are explicitly allowed to handle secrets
_ALLOWED_SECRET_HANDLERS = {
    "app/models/admin_ai_config.py",  # encrypt/decrypt functions
    "app/services/admin_ai_config_service.py",  # CRUD and connection test
    "app/services/model_config_resolver.py",  # resolve model with decrypted key
    "app/services/vector_config_service.py",  # vector config uses same encrypt
}


def audit_secret_exposure() -> dict:
    """Audit source files for potential secret leakage patterns."""
    findings: list[dict] = []
    safe_files: list[str] = []

    for py_file in sorted(BACKEND.rglob("*.py")):
        try:
            source = py_file.read_text()
        except Exception:
            continue

        rel = str(py_file.relative_to(BACKEND.parent.parent))
        file_findings: list[dict] = []

        # Check for patterns that might leak secrets
        lines = source.split("\n")
        for i, line in enumerate(lines, 1):
            lower = line.lower()

            # Logging with api_key or secret
            for pattern, reason in LEAK_PATTERNS:
                if pattern in lower and any(kw in lower for kw in ("log", "print(", "f-string", "trace", "error")):
                    if not _is_comment(line):
                        file_findings.append({
                            "line": i,
                            "pattern": pattern,
                            "reason": reason,
                            "snippet": line.strip()[:120],
                        })

        if file_findings:
            findings.append({
                "file": rel,
                "is_allowed_handler": rel in _ALLOWED_SECRET_HANDLERS,
                "violations": file_findings,
            })
        else:
            safe_files.append(rel)

    return {
        "allowed_secret_handlers": sorted(_ALLOWED_SECRET_HANDLERS),
        "files_with_potential_exposure": findings,
        "safe_files_count": len(safe_files),
        "files_with_exposure_count": len(findings),
        "total_file_count": len(safe_files) + len(findings),
        "note": "Allowed handlers are known to handle secrets (encrypt/decrypt/resolve). "
                "Other files with exposures may need redaction review.",
    }


def _is_comment(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''")


def main():
    audit = audit_secret_exposure()
    out = os.path.join(REPORTS_DIR, "ai_config_secret_audit.json")
    with open(out, "w") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")
    print(f"Files with potential exposure: {audit['files_with_exposure_count']}")
    print(f"Safe files: {audit['safe_files_count']}")


if __name__ == "__main__":
    main()
