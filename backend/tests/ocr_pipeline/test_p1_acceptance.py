"""P1 验收测试 — OCR pipeline 执行边界验证。

这些测试验证 P1 的核心验收条件：
1. PID 隔离：API 主进程不得初始化 PaddleOCR
2. 生产 profile：配置正确拒绝不安全模式
3. OcrRuntimeConfig 校验
4. Gateway 架构一致性
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent.parent / "app"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


# ── 1. PID 隔离测试 ──────────────────────────────────────────────────────────


class TestPidIsolation:
    """验证 API 主进程无法初始化 PaddleOCR。"""

    # OCR_engine.py 的函数，只能在 child process 中调用
    _CHILD_ONLY_FUNCTIONS = frozenset({
        "create_engine_for_child",
    })

    _MAIN_PROCESS_BANNED_IMPORTS = frozenset({
        "create_engine_for_child",
        "OcrEngine",
        "PaddleOCR",
    })

    def test_main_app_no_paddleocr_import(self):
        """``main.py`` and top-level ``__init__.py`` must not import PaddleOCR."""
        for target_name, target_file in [
            ("main.py", BACKEND / "main.py"),
        ]:
            if not target_file.exists():
                pytest.skip(f"{target_file} not found")
            source = target_file.read_text(encoding="utf-8")

            tree = ast.parse(source, filename=str(target_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "PaddleOCR" in alias.name or "OcrEngine" in alias.name:
                            pytest.fail(
                                f"{target_name} imports PaddleOCR or OcrEngine "
                                f"at line {node.lineno}. PaddleOCR must only "
                                f"be initialized in child processes."
                            )
                if isinstance(node, ast.ImportFrom):
                    if node.module and "ocr_engine" in node.module:
                        for alias in node.names:
                            if alias.name in self._MAIN_PROCESS_BANNED_IMPORTS:
                                pytest.fail(
                                    f"{target_name} imports {alias.name} from "
                                    f"ocr_engine at line {node.lineno}. "
                                    f"Engine must only be created in child processes."
                                )

    def test_business_modules_no_ocr_engine_import(self):
        """Business modules must not import engine creation functions."""
        business_modules = [
            "features/pipeline_orchestrator.py",
            "features/question_pipeline.py",
            "features/question_import_writer.py",
            "services/import_service.py",
            "features/batch_image_import_service.py",
            "services/import_pipeline_service.py",
            "services/batch_answer_image_service.py",
        ]

        for mod_path in business_modules:
            target = BACKEND / mod_path
            if not target.exists():
                continue
            source = target.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(target))

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and "ocr_engine" in node.module:
                        for alias in node.names:
                            pytest.fail(
                                f"{mod_path}:{node.lineno} imports "
                                f"{alias.name} from ocr_engine. "
                                f"Business modules must use OCRGateway, "
                                f"not the engine directly."
                            )

    def test_exercise_region_detector_uses_process_pool(self):
        """exercise_region_detector must not import engine directly."""
        target = BACKEND / "features" / "exercise_region_detector.py"
        if not target.exists():
            pytest.skip("exercise_region_detector.py not found")
        source = target.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(target))

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "ocr_engine" in node.module:
                    pytest.fail(
                        f"exercise_region_detector.py:{node.lineno} imports "
                        f"from ocr_engine. Must use ocr_process_pool instead."
                    )


# ── 2. 配置校验测试 ───────────────────────────────────────────────────────────


class TestRuntimeConfigValidation:
    """验证 OcrRuntimeConfig 校验规则。"""

    def test_production_rejects_unsafe_thread_fallback(self):
        """Production + unsafe_thread_fallback=True → ValueError."""
        from app.core.ocr_runtime_config import OcrRuntimeConfig, _validate_config

        bad_cfg = OcrRuntimeConfig(
            enabled=True,
            environment="production",
            unsafe_thread_fallback_enabled=True,
        )
        with pytest.raises(ValueError, match="unsafe_thread_fallback"):
            _validate_config(bad_cfg)

    def test_gpu_requires_spawn(self):
        """use_gpu + fork start_method → ValueError."""
        from app.core.ocr_runtime_config import OcrRuntimeConfig, _validate_config

        bad_cfg = OcrRuntimeConfig(
            enabled=True,
            use_gpu=True,
            start_method="fork",
        )
        with pytest.raises(ValueError, match="start_method"):
            _validate_config(bad_cfg)

    def test_worker_count_must_be_positive(self):
        """worker_count < 1 → ValueError."""
        from app.core.ocr_runtime_config import OcrRuntimeConfig, _validate_config

        bad_cfg = OcrRuntimeConfig(enabled=True, worker_count=0)
        with pytest.raises(ValueError, match="worker_count"):
            _validate_config(bad_cfg)

    def test_execution_timeout_must_be_positive(self):
        """execution_timeout <= 0 → ValueError."""
        from app.core.ocr_runtime_config import OcrRuntimeConfig, _validate_config

        bad_cfg = OcrRuntimeConfig(enabled=True, execution_timeout=0)
        with pytest.raises(ValueError, match="execution_timeout"):
            _validate_config(bad_cfg)

    def test_default_config_is_valid(self):
        """Default dev config must validate successfully."""
        from app.core.ocr_runtime_config import OcrRuntimeConfig, _validate_config

        cfg = OcrRuntimeConfig(enabled=False)
        _validate_config(cfg)  # Should not raise

    def test_runtime_config_is_frozen(self):
        """OcrRuntimeConfig must be immutable."""
        from app.core.ocr_runtime_config import OcrRuntimeConfig

        cfg = OcrRuntimeConfig(enabled=True)
        with pytest.raises(AttributeError, match="cannot assign|frozen"):
            cfg.enabled = False


# ── 3. OcrRuntimeConfig build test ───────────────────────────────────────────


class TestRuntimeConfigBuild:
    """验证运行时配置构建。"""

    def test_build_runtime_config_loads(self):
        """get_runtime_config() must return a valid config."""
        from app.core.ocr_runtime_config import get_runtime_config

        cfg = get_runtime_config()
        assert cfg is not None
        assert hasattr(cfg, "enabled")
        assert hasattr(cfg, "environment")
        assert hasattr(cfg, "worker_count")
        assert hasattr(cfg, "queue_capacity")
        assert hasattr(cfg, "execution_timeout")
        assert hasattr(cfg, "start_method")
        assert hasattr(cfg, "gpu_shards")


# ── 4. AST 架构测试 ─────────────────────────────────────────────────────────


class TestGatewayArchitecture:
    """验证 Gateway 是唯一的 OCR 业务入口。"""

    def test_ocr_service_no_engine_algorithm(self):
        """ocr_service.py must not contain engine algorithm code (double SSOT)."""
        target = BACKEND / "services" / "ocr_service.py"
        source = target.read_text(encoding="utf-8")

        engine_indicators = [
            "def _get_ocr",
            "def _ocr_one_page",
            "def _ocr_prepared_image",
            "from paddleocr import PaddleOCR",
            "_ocr_inference_lock = threading.Lock()",
        ]
        found = [i for i in engine_indicators if i in source]
        assert len(found) == 0, (
            f"ocr_service.py contains engine code: {found}. "
            "Engine code must only live in app/core/ocr_engine.py."
        )

    def test_ocr_engine_has_paddleocr(self):
        """ocr_engine.py must be the single SSOT for OCR algorithm."""
        target = BACKEND / "core" / "ocr_engine.py"
        source = target.read_text(encoding="utf-8")
        assert "PaddleOCR" in source, (
            "ocr_engine.py must contain PaddleOCR initialization. "
            "This is the single source of truth."
        )

    def test_no_engine_singleton_function(self):
        """get_engine_singleton must not exist (removed in P1)."""
        for f in [BACKEND / "core" / "ocr_engine.py",
                  BACKEND / "services" / "ocr_service.py"]:
            if f.exists():
                source = f.read_text(encoding="utf-8")
                if "def get_engine_singleton" in source:
                    pytest.fail(
                        f"{f.name} still defines get_engine_singleton. "
                        "Engine must only be created in child processes via "
                        "create_engine_for_child()."
                    )


# ── 5. 生产环境拒绝 thread fallback 集成测试 ─────────────────────────────────


class TestProductionConfigRejection:
    """验证生产环境拒绝不安全配置。"""

    def test_production_rejects_unsafe_thread_fallback_env(self, monkeypatch):
        """Production profile with OCR_UNSAFE_THREAD_FALLBACK_ENABLED=1 must fail."""
        monkeypatch.setenv("DEPLOYMENT_PROFILE", "cloud_api")
        monkeypatch.setenv("OCR_UNSAFE_THREAD_FALLBACK_ENABLED", "1")
        monkeypatch.setenv("OCR_ENABLED", "1")

        # Reset runtime config singleton
        from app.core.ocr_runtime_config import get_runtime_config, reset_runtime_config
        reset_runtime_config()

        with pytest.raises(ValueError, match="unsafe_thread_fallback"):
            get_runtime_config()

    def test_production_without_unsafe_fallback_is_valid(self, monkeypatch):
        """Production profile without unsafe fallback must validate successfully."""
        monkeypatch.setenv("DEPLOYMENT_PROFILE", "cloud_api")
        monkeypatch.setenv("OCR_UNSAFE_THREAD_FALLBACK_ENABLED", "0")
        monkeypatch.setattr("app.core.ocr_runtime_config.settings.OCR_EXECUTION_BACKEND", "disabled")
        monkeypatch.setattr("app.core.ocr_runtime_config.settings.OCR_REMOTE_TOKEN", "test-token")

        from app.core.ocr_runtime_config import get_runtime_config, reset_runtime_config
        reset_runtime_config()

        cfg = get_runtime_config()
        assert cfg.environment == "production"
        assert not cfg.unsafe_thread_fallback_enabled
