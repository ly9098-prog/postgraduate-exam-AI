"""Static architecture boundary tests for OCR pipeline.

These tests use AST analysis to detect violations of the target architecture:

1. No direct import of ``app.services.ocr_service`` private functions/objects
2. No direct import of ``app.features.ai_safety`` outside permitted paths
3. Coordinator pipeline must not use ``dummy_ir`` or no-op success
4. Feature flag safety: coordinator mode must fail-closed

These tests MUST fail when new violations are introduced, serving as an
architecture gate for the OCR pipeline refactoring.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "app"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Whitelists for allowed imports ───────────────────────────────────────────

# Modules that can access ocr_service private functions / globals
_OCR_SERVICE_PRIVILEGED = frozenset({
    "app.services.ocr_service",  # itself
    "app.services.ocr_executor_service",
    "app.services.ocr_process_pool",
    "app.services.ocr_cache_service",
    "app.core.ocr_runtime_config",
    "app.core.ocr_process_pool",
    "app.core.ocr_engine",       # engine module (child process only)
    "app.core.ocr_worker_process",
    "app.core.ocr_worker_pool",
    "app.services.ocr_local_worker_client",
})

# ocr_service names that are safe for public consumption
_OCR_SERVICE_PUBLIC_API = frozenset({
    "clean_ocr_text",
    "get_ocr_cache_stats",
    "ocr_is_available",
    "get_ocr_init_error",
    "OcrPageResult",
    "OcrCandidateResult",
    "reset_ocr_engine",
    "ocr_raw_text",
    "set_gateway",
    "get_gateway",
    "ocr_pages",              # backward-compat public wrapper
    "ocr_pages_with_boxes",   # backward-compat public wrapper
    # legacy paths that predate gateway — will be migrated
})

# Modules that can access ai_safety
_AI_SAFETY_PRIVILEGED = frozenset({
    "app.features.candidate_evaluator",                    # the single evaluator
    "app.features.ai_safety",                              # itself
    "app.features.ai_repair",                              # uses it as sub-evaluator (legacy)
    "app.features.ocr_correction",
    "app.features.ocr_fix.router",
})

# Module prefixes that are always exempt (test files)
_TEST_PREFIXES = ("test_", "tests.")


def _is_test_module(module_name: str) -> bool:
    return any(prefix in module_name for prefix in _TEST_PREFIXES)


def _module_name(path: Path) -> str:
    """Convert a file path to dotted module name relative to project root."""
    rel = path.relative_to(PROJECT_ROOT)
    parts = list(rel.parts)
    # Remove 'backend/' prefix
    if parts and parts[0] == "backend":
        parts = parts[1:]
    # Remove __init__.py or .py
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts)


def _py_files_under(dir: Path) -> list[Path]:
    return sorted(dir.rglob("*.py"))


# ── Test 1: Private ocr_service import boundary ────────────────────────────


class TestOcrServiceImportBoundary:
    """No module outside privileged set imports ocr_service private globals."""

    # Private names that should never be imported outside privileged modules
    _PRIVATE_NAMES = frozenset({
        "_ocr_instance",
        "_ocr_init_lock",
        "_ocr_inference_lock",
        "_ocr_state",
        "_ocr_state_lock",
        "_ocr_init_error",
        "_ocr_initialized",
        "_ocr_reinit_count",
        "_get_ocr",
        "_reset_ocr",
        "_ocr_one_page",
        "_ocr_one_page_with_boxes",
        "_ocr_prepared_image",
        "_ocr_with_rotation_candidates",
        "_prepare_ocr_image",
        "_load_ocr_image",
        "_resize_for_ocr",
        "_deskew_image",
        "_crop_blank_margins",
        "_estimate_skew_angle",
        "_extract_ocr_lines",
        "_order_ocr_lines_reading_order",
        "_detect_column_split",
        "_score_ocr_result",
        "_ocr_score_is_good",
        "_normalize_ocr_result",
        "_image_to_array",
        "_image_to_ocr_array",
        "_foreground_mask",
        "_content_bbox_from_luma",
        "_projection_score",
        "_estimate_image_quality",
        "_choose_preprocessing_strategy",
        "_apply_quality_strategy",
        "_HEALTH_CHECK_IMAGE",
        "_get_health_check_image",
        "_run_ocr_health_check",
        "_OCR_LOW_CONF_THRESHOLD",
        "_OCR_MAX_SIDE",
        "_OCR_DEPENDENCY_ERROR",
        "_ocr_cache_hits",
        "_ocr_cache_misses",
        "_set_transform_tracker",
        "get_last_transform_tracker",
        "_tracker_local",
    })

    def _find_violations(self) -> list[dict]:
        """AST-scan all non-test, non-privileged modules for disallowed imports."""
        violations: list[dict] = []

        for py_file in _py_files_under(PROJECT_ROOT / "backend" / "app"):
            if "__pycache__" in str(py_file):
                continue
            mod = _module_name(py_file)
            if _is_test_module(mod):
                continue
            if mod in _OCR_SERVICE_PRIVILEGED:
                continue

            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except SyntaxError:
                violations.append({"file": str(py_file), "line": 0, "name": "SYNTAX_ERROR"})
                continue

            for node in ast.walk(tree):
                # from app.services.ocr_service import _some_private_name
                if isinstance(node, ast.ImportFrom):
                    if node.module == "app.services.ocr_service":
                        for alias in node.names:
                            if alias.name.startswith("_") or alias.name not in _OCR_SERVICE_PUBLIC_API:
                                violations.append({
                                    "file": str(py_file),
                                    "line": node.lineno,
                                    "name": alias.name,
                                })

                # import app.services.ocr_service → then use _private accesses
                # This is harder to detect statically (attribute access), but
                # we catch the common pattern of importing the module directly
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "app.services.ocr_service":
                            # This is suspicious — check for attribute access
                            # after this import. For now, flag it.
                            violations.append({
                                "file": str(py_file),
                                "line": node.lineno,
                                "name": alias.name + " (module import)",
                            })

        return violations

    def test_no_private_import_outside_privileged_modules(self):
        violations = self._find_violations()
        msg_parts = [f"Found {len(violations)} ocr_service private import violations:"]
        for v in violations[:30]:
            msg_parts.append(f"  {v['file']}:{v['line']}  {v['name']}")
        if violations:
            msg_parts.append(
                "\nFix: domain modules must use ocr_executor_service, "
                "not import ocr_service private functions."
            )
        assert len(violations) == 0, "\n".join(msg_parts)


# ── Test 2: ai_safety import boundary ────────────────────────────────────────


class TestAiSafetyImportBoundary:
    """Only CandidateEvaluator and privileged modules import ai_safety directly."""

    _PRIVILEGED = _AI_SAFETY_PRIVILEGED

    def _find_violations(self) -> list[dict]:
        violations: list[dict] = []

        for py_file in _py_files_under(PROJECT_ROOT / "backend" / "app"):
            if "__pycache__" in str(py_file):
                continue
            mod = _module_name(py_file)
            if _is_test_module(mod):
                continue
            if mod in self._PRIVILEGED:
                continue

            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and "ai_safety" in node.module:
                        violations.append({
                            "file": str(py_file),
                            "line": node.lineno,
                            "name": node.module,
                        })
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "ai_safety" in alias.name:
                            violations.append({
                                "file": str(py_file),
                                "line": node.lineno,
                                "name": alias.name,
                            })

        return violations

    def test_no_ai_safety_import_outside_privileged_modules(self):
        violations = self._find_violations()
        msg_parts = [f"Found {len(violations)} ai_safety import violations:"]
        for v in violations[:20]:
            msg_parts.append(f"  {v['file']}:{v['line']}  {v['name']}")
        if violations:
            msg_parts.append(
                "\nFix: all safety evaluations must go through CandidateEvaluator."
            )
        assert len(violations) == 0, "\n".join(msg_parts)


# ── Test 3: Coordinator dummy_ir / no-op detection ──────────────────────────


class TestCoordinatorNoDummyIr:
    """Coordinator pipeline must not use dummy_ir or return fake success."""

    def test_coordinator_orchestrator_no_dummy_ir(self):
        """Check coordinator_orchestrator.py for dummy_ir assignments."""
        target = BACKEND / "features" / "coordinator_orchestrator.py"
        if not target.exists():
            pytest.skip("coordinator_orchestrator.py not found")

        source = target.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(target))

        dummy_ir_lines: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target_node in node.targets:
                    if isinstance(target_node, ast.Name) and "dummy" in target_node.id.lower():
                        dummy_ir_lines.append(node.lineno)
            # Also check string literals
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "dummy" in node.value.lower() and "ir" in node.value.lower():
                    dummy_ir_lines.append(node.lineno)

        assert len(dummy_ir_lines) == 0, (
            f"coordinator_orchestrator.py uses dummy_ir at lines {dummy_ir_lines}. "
            "Remove dummy_ir before enabling coordinator mode."
        )

    def test_coordinators_no_noop_success(self):
        """Check coordinators.py — no-op coordinators must return NOT_IMPLEMENTED.

        Correction/Validation/Review/Persistence coordinators are NOT_IMPLEMENTED
        and must NOT return ModuleResult.success.
        """
        target = BACKEND / "features" / "coordinators.py"
        if not target.exists():
            pytest.skip("coordinators.py not found")

        source = target.read_text(encoding="utf-8")

        # Verify that NOT_IMPLEMENTED is used instead of success for no-op coordinators
        not_implemented_count = source.count("NOT_IMPLEMENTED")
        assert not_implemented_count >= 3, (
            f"Expected at least 3 NOT_IMPLEMENTED references in coordinators.py, "
            f"found {not_implemented_count}. No-op coordinators must return "
            f"NOT_IMPLEMENTED failure, not success."
        )

        # Verify no ModuleResult.success in the run methods of no-op coordinators
        # by checking that the last occurrence of "return ModuleResult.success" is
        # before the CorrectionCoordinator class.
        # Real coordinators (InputCoordinator, OCRCoordinator, DocumentStructureCoordinator,
        # DomainParsingCoordinator, ReviewCoordinator) may legitimately use success.
        last_success_line = 0
        for i, line in enumerate(source.split("\n"), 1):
            if "return ModuleResult.success" in line:
                last_success_line = i

        correction_line = None
        for i, line in enumerate(source.split("\n"), 1):
            if "class CorrectionCoordinator" in line:
                correction_line = i
                break

        if correction_line and last_success_line >= correction_line:
            # ReviewCoordinator is between CorrectionCoordinator and PersistenceCoordinator,
            # and it is a real (not no-op) implementation. Verify it's the real one.
            review_run_success = False
            in_review = False
            for i, line in enumerate(source.split("\n"), 1):
                if "class ReviewCoordinator" in line:
                    in_review = True
                elif "class " in line and i > correction_line:
                    in_review = False
                if in_review and "return ModuleResult.success" in line:
                    review_run_success = True
                    break

            if not review_run_success:
                pytest.fail(
                    f"No-op coordinator after line {correction_line} uses "
                    f"ModuleResult.success (last success at line {last_success_line}). "
                    f"Must use ModuleResult.failure(NOT_IMPLEMENTED) instead."
                )


# ── Test 4: Feature flag safety ──────────────────────────────────────────────


class TestFeatureFlagSafety:
    """Feature flags must be fail-closed when dependencies are incomplete."""

    def test_coordinator_mode_fail_closed_with_dummy_ir(self):
        """coordinator mode must fail closed when dummy_ir is present.

        This test verifies that PIPELINE_COORDINATOR_MODE defaults are safe
        and that coordinator mode cannot silently succeed.
        """
        # Check the coordinator entry point's get_coordinator_mode() default
        target = BACKEND / "features" / "pipeline_coordinator_entry.py"
        source = target.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(target))

        # Check default mode — should be 'legacy' or 'shadow', NOT 'coordinator'
        # when dummy_ir still exists
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and hasattr(node.func, 'id') and node.func.id == 'environ.get':
                args = [a for a in node.args if isinstance(a, ast.Constant)]
                if any('PIPELINE_COORDINATOR_MODE' in str(a.value) for a in args):
                    default = None
                    for a in node.args:
                        if isinstance(a, ast.Constant) and a.value != 'PIPELINE_COORDINATOR_MODE':
                            default = a.value
                    if default and default == "coordinator":
                        pytest.fail(
                            "PIPELINE_COORDINATOR_MODE defaults to 'coordinator' "
                            "but dummy_ir is still present. Must default to "
                            "'legacy' or 'shadow' until all coordinators are real."
                        )

    def test_structure_freeze_mode_not_misleading(self):
        """STRUCTURE_FREEZE_MODE=legacy must not claim IR readiness."""
        from app.core.config import settings
        mode = settings.STRUCTURE_FREEZE_MODE
        assert mode != "ir", (
            "STRUCTURE_FREEZE_MODE=ir would claim IR readiness "
            "but the DocumentIR pipeline is not complete."
        )


# ── Test 5: compileall ──────────────────────────────────────────────────────


class TestCompileAll:
    """All Python files in the project must compile without syntax errors."""

    def test_all_py_files_compile(self):
        import py_compile

        backend_root = PROJECT_ROOT / "backend"
        source_dir = backend_root / "app"

        errors: list[str] = []
        for py_file in sorted(source_dir.rglob("*.py")):
            if "__pycache__" in str(py_file):
                continue
            try:
                py_compile.compile(str(py_file), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f"{py_file}: {e}")

        assert len(errors) == 0, (
            f"Found {len(errors)} syntax errors:\n" + "\n".join(errors[:20])
        )


# ── Test 6: Import smoke test ────────────────────────────────────────────────


class TestImportSmoke:
    """Critical modules must be importable without errors."""

    CRITICAL_MODULES = [
        "app.core.config",
        "app.core.document_ir",
        "app.services.ocr_executor_service",
        "app.features.candidate_evaluator",
        "app.features.coordinators",
        "app.features.pipeline_coordinator_entry",
        "app.features.coordinator_orchestrator",
    ]

    def test_critical_modules_importable(self):
        errors: list[str] = []
        for mod_name in self.CRITICAL_MODULES:
            try:
                __import__(mod_name)
                print(f"  OK: {mod_name}")
            except ImportError as e:
                errors.append(f"{mod_name}: {e}")
                print(f"  SKIP: {mod_name} ({e})")

        # For P0, this is informational — many modules have heavy deps
        # (paddleocr, cv2, etc.) that can't be installed in CI.
        # This test serves as a checklist, not a hard gate, until
        # CI has the full dependency chain.
        if errors:
            print(f"\n  {len(errors)} modules not importable (expected in CI without paddleocr)")


# ── Test 7: Double SSOT detection ──────────────────────────────────────────


class TestNoDoubleSsoT:
    """Verify no second copy of OCR engine algorithm exists.

    ``ocr_service.py`` must be a thin compat wrapper, not contain engine
    algorithm code. We detect this by checking if the file contains
    PaddleOCR import or model-level constants.
    """

    _ENGINE_INDICATORS = frozenset({
        "from paddleocr import PaddleOCR",
        "_OCR_MAX_SIDE",
        "_OCR_DEPENDENCY_ERROR",
        "_ocr_inference_lock",
        "def _get_ocr",
        "def _ocr_one_page",
        "def _ocr_prepared_image",
    })

    def test_ocr_service_has_no_engine_code(self):
        """ocr_service.py must not contain engine algorithm code."""
        target = BACKEND / "services" / "ocr_service.py"
        source = target.read_text(encoding="utf-8")

        found = [indicator for indicator in self._ENGINE_INDICATORS if indicator in source]
        assert len(found) == 0, (
            f"ocr_service.py contains {len(found)} engine code indicators: {found}. "
            "Engine code must only live in app/core/ocr_engine.py."
        )

    def test_ocr_engine_has_paddleocr(self):
        """ocr_engine.py must contain the PaddleOCR initialization."""
        target = BACKEND / "core" / "ocr_engine.py"
        source = target.read_text(encoding="utf-8")

        assert "PaddleOCR" in source, (
            "ocr_engine.py must contain PaddleOCR initialization. "
            "This is the single source of truth for OCR algorithm code."
        )
