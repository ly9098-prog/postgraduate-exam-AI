"""Sprint 4B — Cloud profile must not import paddleocr at module level.

On cloud_api, paddleocr is not installed. Top-level imports would crash
the server at startup. Imports inside functions (guarded by profile checks
or try/except) are fine.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


class TestNoPaddleOcrTopLevelImport:
    def test_no_top_level_paddle_ocr_import(self) -> None:
        """Scan app/ for top-level paddleocr imports (inside functions is OK)."""
        app_dir = Path(__file__).resolve().parent.parent / "app"
        violations: list[str] = []

        for py_file in app_dir.rglob("*.py"):
            rel = str(py_file.relative_to(app_dir))

            # Exclude test files, cache, and ocr_worker (expected to import paddleocr)
            if (
                "tests" in py_file.parts
                or "__pycache__" in py_file.parts
                or "ocr_worker" in py_file.parts
            ):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
            except Exception:
                continue

            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue

            # Only check module-level nodes (iter_child_nodes, not walk)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "paddleocr" or alias.name.startswith("paddleocr."):
                            violations.append(
                                f"{rel}: `import {alias.name}` at module level"
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module and (
                        node.module == "paddleocr" or node.module.startswith("paddleocr.")
                    ):
                        names = ", ".join(
                            a.name for a in node.names
                        ) if node.names else "*"
                        violations.append(
                            f"{rel}: `from {node.module} import {names}` at module level"
                        )

        assert not violations, (
            "Top-level paddleocr imports found (crash risk on cloud_api):\n"
            + "\n".join(violations)
        )

    def test_no_paddle_at_startup(self) -> None:
        """After importing core modules, paddleocr must not be in sys.modules."""
        # Other tests may have already imported paddle/paddleocr (ordering
        # pollution). Remove them so this check reflects only what the core
        # module imports add, not earlier test activity.
        saved = {}
        for mod in list(sys.modules):
            if mod.startswith(("paddle", "paddleocr")):
                saved[mod] = sys.modules.pop(mod)

        # Import core modules that the app loads at startup
        import app.core.config  # noqa: F401
        import app.core.deployment_profile  # noqa: F401
        import app.features.runtime_capabilities  # noqa: F401

        assert (
            "paddleocr" not in sys.modules
        ), "paddleocr was imported during core module loading — must be lazy"

        # Restore popped modules so later tests importing them (e.g.
        # paddleocr_vl_client) don't get a NEW module object while code imported
        # earlier still holds the old one — that split breaks patch() identity.
        for mod, obj in saved.items():
            sys.modules[mod] = obj
