"""Sprint 4C: Guard against new legacy OCR call-site proliferation.

Existing code in ocr_adapter.py is allowed to use rec_texts/dt_polys.
This test ensures no NEW files introduce these patterns.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent / "app"
FEATURES_DIR = APP_DIR / "features"

# Files explicitly allowed to use legacy patterns.
# These predate DocumentIR and use normalized_blocks / rec_texts / dt_polys
# as part of the pre-DocumentIR block format. The test guards against
# NEW files introducing these patterns.
ALLOWED_FILES = {
    "ocr_adapter.py",
    "ocr_correction_common.py",
    "ocr_gateway.py",
    "pipeline_orchestrator.py",
    "answer_matcher.py",
    "layout_reconstruction.py",
    "page_classifier.py",
    "structure_analyzer.py",
    "question_splitter.py",
    "visual_boundary_detector.py",
    "table_region_detector.py",
    "text_normalizer.py",
    "layout_stage.py",
    "match_stage.py",
    "structure_freeze_stage.py",
}

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


def _collect_features_py_files() -> list[str]:
    """Collect .py files under app/features/, excluding disallowed dirs."""
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(str(FEATURES_DIR)):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fname in filenames:
            if not fname.endswith(".py") or fname.startswith("__"):
                continue
            if fname in ALLOWED_FILES:
                continue
            files.append(os.path.join(dirpath, fname))
    return files


def _scan_for_names(
    filepath: str, patterns: list[str],
) -> list[tuple[int, str, str]]:
    """AST-scan a file for variable/attribute names matching patterns.

    Returns list of (lineno, node_type, matched_name).
    """
    hits: list[tuple[int, str, str]] = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except (OSError, UnicodeDecodeError):
        return hits

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return hits

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            for p in patterns:
                if node.id == p or p in node.id:
                    hits.append((node.lineno, "name", node.id))
        if isinstance(node, ast.Attribute):
            for p in patterns:
                if node.attr == p or p in node.attr:
                    hits.append((node.lineno, "attr", node.attr))

    return hits


class TestNoNewLegacyCallSites:
    """Verify no new legacy OCR call sites are introduced."""

    def test_no_new_rec_texts_dt_polys_outside_allowed(self):
        """Scan app/features/ for rec_texts/dt_polys in non-allowed files."""
        patterns = ["rec_texts", "dt_polys", "rec_scores"]

        all_hits: list[str] = []
        for filepath in sorted(_collect_features_py_files()):
            hits = _scan_for_names(filepath, patterns)
            for lineno, ntype, matched in hits:
                rel = os.path.relpath(filepath, str(APP_DIR))
                all_hits.append(f"  {rel}:{lineno}: {ntype} '{matched}'")

        if all_hits:
            report = (
                "Found legacy OCR field references in new files "
                "(outside allowed adapters):\n"
                + "\n".join(all_hits)
                + "\n\nThese patterns should only exist in adapter files."
            )
            assert False, report

    def test_no_new_normalized_blocks_outside_allowed(self):
        """Scan app/features/ for 'normalized_blocks' in non-allowed files."""
        patterns = ["normalized_blocks", "blocks_to_normalized"]

        all_hits: list[str] = []
        for filepath in sorted(_collect_features_py_files()):
            hits = _scan_for_names(filepath, patterns)
            for lineno, ntype, matched in hits:
                rel = os.path.relpath(filepath, str(APP_DIR))
                all_hits.append(f"  {rel}:{lineno}: {ntype} '{matched}'")

        if all_hits:
            report = (
                "Found 'normalized_blocks'/'blocks_to_normalized' in new files:\n"
                + "\n".join(all_hits)
                + "\n\nThese should only appear in compatibility bridges."
            )
            assert False, report

    def test_allowed_files_exist(self):
        """Verify all allowed files actually exist (search recursively)."""
        for fname in ALLOWED_FILES:
            found = False
            for dirpath, _dirnames, filenames in os.walk(str(FEATURES_DIR)):
                if fname in filenames:
                    found = True
                    break
            # Also check services/
            services_dir = APP_DIR / "services"
            if not found and services_dir.exists():
                for dirpath, _dirnames, filenames in os.walk(str(services_dir)):
                    if fname in filenames:
                        found = True
                        break
            assert found, f"Allowed file {fname} not found under app/"

    def test_features_directory_populated(self):
        """Sanity: features directory has .py files to scan."""
        files = _collect_features_py_files()
        assert len(files) > 0, "No Python files found in features/"

    def test_no_raw_patterns_in_coordinators(self):
        """coordinators.py must not reference raw OCR fields."""
        coord_path = FEATURES_DIR / "coordinators.py"
        if coord_path.exists():
            hits = _scan_for_names(
                str(coord_path),
                ["rec_texts", "dt_polys", "normalized_blocks"],
            )
            if hits:
                detail = "; ".join(
                    f"L{ln}:{ntype}='{m}'" for ln, ntype, m in hits
                )
                assert False, f"coordinators.py must not ref raw fields: {detail}"

    def test_no_raw_patterns_in_coordinator_orchestrator(self):
        """coordinator_orchestrator.py must not reference raw OCR fields."""
        orch_path = FEATURES_DIR / "coordinator_orchestrator.py"
        if orch_path.exists():
            hits = _scan_for_names(
                str(orch_path),
                ["rec_texts", "dt_polys", "normalized_blocks"],
            )
            if hits:
                detail = "; ".join(
                    f"L{ln}:{ntype}='{m}'" for ln, ntype, m in hits
                )
                assert False, (
                    f"coordinator_orchestrator.py must not ref raw fields: {detail}"
                )

    def test_ocr_adapter_is_allowed(self):
        """ocr_adapter.py is in the allowed set (sanity check)."""
        assert "ocr_adapter.py" in ALLOWED_FILES
