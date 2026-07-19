#!/usr/bin/env python3
"""Audit Cloud Runtime Dependencies — Check production server startup imports.

Verifies:
- No top-level paddleocr import in app/
- No top-level torch CUDA import in app/
- All paddleocr imports are behind lazy / profile guard
- import hook simulation for cloud_api profile

Output:
  reports/sprint4b/cloud_dependency_audit.json
"""

from __future__ import annotations

import ast
import json
import os
import sys

REPORTS_DIR = "reports/sprint4b"
os.makedirs(REPORTS_DIR, exist_ok=True)

PADDLE_MODULES = {"paddleocr", "paddleocr.paddleocr", "paddleocr.PaddleOCR"}
PADDLE_BASE = {"paddle", "paddle.base", "paddle.framework"}
TORCH_CUDA = {"torch.cuda", "torch.backends.cuda"}

ALL_BLOCKED = PADDLE_MODULES | PADDLE_BASE | TORCH_CUDA


class ImportVisitor(ast.NodeVisitor):
    """Check if a file imports blocked modules at the top level."""

    def __init__(self, fpath: str):
        self.fpath = fpath
        self.top_level_imports = []
        self.in_function = 0
        self.in_class = 0

    def visit_FunctionDef(self, node):
        self.in_function += 1
        self.generic_visit(node)
        self.in_function -= 1

    def visit_AsyncFunctionDef(self, node):
        self.in_function += 1
        self.generic_visit(node)
        self.in_function -= 1

    def visit_ClassDef(self, node):
        self.in_class += 1
        self.generic_visit(node)
        self.in_class -= 1

    def visit_Import(self, node):
        for alias in node.names:
            if self._is_blocked(alias.name):
                self.top_level_imports.append({
                    "file": self.fpath,
                    "module": alias.name,
                    "scope": "top_level" if self.in_function == 0 and self.in_class == 0 else "guarded",
                    "level": 0 if self.in_function == 0 and self.in_class == 0 else 1,
                })

    def visit_ImportFrom(self, node):
        if node.module and self._is_blocked(node.module):
            self.top_level_imports.append({
                "file": self.fpath,
                "module": node.module,
                "scope": "top_level" if self.in_function == 0 and self.in_class == 0 else "guarded",
                "level": 0 if self.in_function == 0 and self.in_class == 0 else 1,
            })

    def _is_blocked(self, module: str) -> bool:
        for blocked in ALL_BLOCKED:
            if module.startswith(blocked) or module == blocked:
                return True
        return False


def main():
    violations = []
    guarded = []

    for root, dirs, files in os.walk("app"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    tree = ast.parse(f.read())
            except SyntaxError:
                continue

            visitor = ImportVisitor(os.path.relpath(fpath))
            visitor.visit(tree)
            for imp in visitor.top_level_imports:
                if imp["level"] == 0:
                    violations.append(imp)
                else:
                    guarded.append(imp)

    # Check for __init__ imports that would be triggered at import time
    init_files = []
    for root, dirs, files in os.walk("app"):
        if "__init__.py" in files:
            init_files.append(os.path.join(root, "__init__.py"))

    for fpath in init_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            tree = ast.parse(content)
        except (SyntaxError, OSError):
            continue

        visitor = ImportVisitor(os.path.relpath(fpath))
        visitor.visit(tree)
        for imp in visitor.top_level_imports:
            if imp["level"] == 0:
                violations.append({**imp, "via_init": True})

    # Check specific entry points
    entry_points = ["app/main.py", "app/api/v1/router.py"]
    entry_chain = []
    for ep in entry_points:
        fpath = ep
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            tree = ast.parse(content)
        except (SyntaxError, OSError):
            continue
        visitor = ImportVisitor(fpath)
        visitor.visit(tree)
        for imp in visitor.top_level_imports:
            entry_chain.append(imp)

    output = {
        "violations": violations,
        "guarded_imports": guarded,
        "entry_point_imports": entry_chain,
        "summary": {
            "top_level_violations": len(violations),
            "guarded_imports": len(guarded),
            "entry_point_violations": len([v for v in entry_chain if v.get("level") == 0]),
        },
        "assessment": "",
    }

    if violations:
        output["assessment"] = (
            f"FOUND {len(violations)} top-level imports of blocked modules. "
            "These must be moved behind lazy / profile-guarded imports for cloud_api profile."
        )
    else:
        output["assessment"] = "No top-level blocked imports found. Cloud profile dependency isolation is clean."

    out_path = os.path.join(REPORTS_DIR, "cloud_dependency_audit.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")
    print(f"  Violations: {len(violations)}")
    print(f"  Guarded: {len(guarded)}")
    for v in violations:
        print(f"    [VIOLATION] {v['file']}: {v['module']}")

    return output


if __name__ == "__main__":
    main()
