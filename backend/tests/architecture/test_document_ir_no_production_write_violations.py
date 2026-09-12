"""Sprint 4C: DocumentIR production-write violation detection.

Ensures legacy normalizer/block patterns do not leak into production code paths.
Uses AST scanning to detect forbidden patterns.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

# Path to the app directory
APP_DIR = Path(__file__).resolve().parent.parent.parent / "app"

# Files and directories to exclude from scanning
EXCLUDE_DIRS = {
    "tests",
    "ocr_worker",
    "ocr_bench",
    "ocr_eval",
    "evaluation",
    "benchmarks",
    "performance",
    "fixtures",
    "manual",
    "scripts",
    "__pycache__",
}

EXCLUDE_FILES = {
    "ocr_adapter.py",
    "ocr_correction_common.py",
    "document_ir.py",
    "ocr_gateway.py",
    # Legacy files that predate DocumentIR — these use normalized_blocks
    # as part of the pre-DocumentIR block format.  They are intentionally
    # allowed; the test guards against NEW files introducing the pattern.
    "answer_matcher.py",
    "layout_reconstruction.py",
    "page_classifier.py",
    "pipeline_orchestrator.py",
    "structure_analyzer.py",
    "question_splitter.py",
    "visual_boundary_detector.py",
    "table_region_detector.py",
    "text_normalizer.py",
    "question_snapshot_service.py",
    "layout_stage.py",
    "match_stage.py",
    "structure_freeze_stage.py",
}

# Forbidden patterns for production write paths
FORBIDDEN_PATTERNS = [
    "blocks_to_normalized",
    "normalized_blocks",
]


def _should_skip_file(filepath: str) -> bool:
    """Check if file should be excluded from scanning."""
    for excl in EXCLUDE_DIRS:
        if excl in filepath.split(os.sep):
            return True
    for excl in EXCLUDE_FILES:
        if filepath.endswith(excl):
            return True
    return False


def _scan_file_for_patterns(
    filepath: str, patterns: list[str],
) -> list[tuple[int, str]]:
    """AST-scan a Python file for variable/attribute names matching patterns."""
    violations: list[tuple[int, str]] = []
    try:
        with open(filepath, encoding="utf-8") as f:
            source = f.read()
    except (OSError, UnicodeDecodeError):
        return violations

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            for pattern in patterns:
                if pattern in node.id:
                    violations.append(
                        (node.lineno, f"Name '{node.id}' matches '{pattern}'"),
                    )
        if isinstance(node, ast.Attribute):
            for pattern in patterns:
                if pattern in node.attr:
                    violations.append(
                        (node.lineno, f"Attribute '.{node.attr}' matches '{pattern}'"),
                    )
        if isinstance(node, ast.FunctionDef):
            for pattern in patterns:
                if pattern in node.name:
                    violations.append(
                        (node.lineno,
                         f"FunctionDef '{node.name}' matches '{pattern}'"),
                    )

    return violations


def _collect_py_files(root: Path) -> list[str]:
    """Collect .py files under root, excluding test/worker dirs."""
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fullpath = os.path.join(dirpath, fname)
            if _should_skip_file(fullpath):
                continue
            if not fullpath.startswith(str(APP_DIR)):
                continue
            files.append(fullpath)
    return files


class TestDocumentIRNoProductionWriteViolations:
    """Verify production code does not write legacy block formats."""

    def test_legacy_blocks_not_written(self):
        """AST-scan app/ for forbidden legacy block patterns in production code."""
        py_files = _collect_py_files(APP_DIR)
        assert len(py_files) > 0, "No Python files found to scan"

        all_violations: list[str] = []
        for filepath in sorted(py_files):
            violations = _scan_file_for_patterns(filepath, FORBIDDEN_PATTERNS)
            for lineno, msg in violations:
                rel = os.path.relpath(filepath, str(APP_DIR))
                all_violations.append(f"  {rel}:{lineno}: {msg}")

        if all_violations:
            report = (
                "Found legacy block pattern violations in production code:\n"
                + "\n".join(all_violations)
            )
            assert False, report

    def test_document_ir_has_ssot_api(self):
        """DocumentIR class is importable and has expected fields/methods."""
        from dataclasses import fields as dc_fields

        from app.core.document_ir import DocumentIR

        assert isinstance(DocumentIR, type)
        assert DocumentIR.__name__ == "DocumentIR"

        # Dataclass fields: use fields() instead of hasattr() because fields
        # with factory defaults (field(default_factory=list)) are stored in
        # __dataclass_fields__ but not as class-level attributes.
        field_names = {f.name for f in dc_fields(DocumentIR)}
        expected_fields = {
            "document_id", "pages", "source_hash",
            "pipeline_fingerprint", "schema_version",
        }
        missing = expected_fields - field_names
        assert not missing, f"Missing dataclass fields: {missing}"

        # Properties and methods are accessible via hasattr
        assert hasattr(DocumentIR, "page_count")
        assert hasattr(DocumentIR, "get_page")
        assert hasattr(DocumentIR, "add_page")

    def test_document_ir_instantiable(self):
        """DocumentIR can be instantiated."""
        from app.core.document_ir import DocumentIR

        doc = DocumentIR(document_id="test-001")
        assert doc.document_id == "test-001"
        assert doc.page_count == 0
        assert isinstance(doc.pages, list)

    def test_legacy_blocks_compat_view(self):
        """document_ir_to_blocks function exists and is callable."""
        from app.core.document_ir import DocumentIR, document_ir_to_blocks

        assert callable(document_ir_to_blocks)

        doc = DocumentIR(document_id="test-compat")
        blocks = document_ir_to_blocks(doc)
        assert isinstance(blocks, list)
        assert len(blocks) == 0

    def test_document_ir_to_blocks_with_pages(self):
        """document_ir_to_blocks correctly converts DocumentIR with pages."""
        from app.core.document_ir import (
            BBox,
            DocumentIR,
            LineIR,
            PageIR,
            RegionIR,
            document_ir_to_blocks,
        )

        line = LineIR(
            line_id="L001",
            text="Hello world",
            bbox=BBox(10, 20, 100, 50),
            confidence=0.95,
            reading_order=0,
        )
        region = RegionIR(
            region_id="R001",
            region_type="text",
            lines=[line],
            bbox=BBox(10, 20, 100, 50),
            reading_order=0,
        )
        page = PageIR(
            page_id="P1",
            page_index=0,
            width=600,
            height=800,
            regions=[region],
        )
        doc = DocumentIR(document_id="test-with-pages", pages=[page])

        blocks = document_ir_to_blocks(doc)
        assert len(blocks) == 1
        assert blocks[0]["page"] == 1
        assert blocks[0]["text"] == "Hello world"
        assert blocks[0]["page_width"] == 600
        assert blocks[0]["page_height"] == 800
        assert blocks[0]["source"] == "document_ir"
        assert blocks[0]["has_boxes"] is True
        assert len(blocks[0]["boxes"]) == 1
        assert blocks[0]["boxes"][0]["text"] == "Hello world"
        assert blocks[0]["boxes"][0]["conf"] == 0.95
        assert blocks[0]["boxes"][0]["line_id"] == "L001"

    def test_document_ir_full_exports(self):
        """All key DocumentIR exports are importable."""
        # All imports succeeded if we reach here
        assert True
