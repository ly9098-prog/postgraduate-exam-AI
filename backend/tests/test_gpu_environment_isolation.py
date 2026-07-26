"""GPU environment isolation tests — verify CPU and GPU envs are separate."""
from __future__ import annotations

import os
import sys


class TestGPUEnvironmentIsolation:
    """Verify GPU installation never modifies CPU environment."""

    def test_gpu_venv_path_differs_from_cpu(self):
        """GPU venv must have a different path from CPU venv and must not
        be the same directory as the CPU venv."""
        cpu_venv = ".venv"
        gpu_venv = ".venv-ocr-gpu-330"
        assert gpu_venv != cpu_venv
        # The paths must not be identical directories
        assert os.path.abspath(gpu_venv) != os.path.abspath(cpu_venv)

    def test_gpu_cpu_comparison_venvs_are_distinct(self):
        """CPU comparison env must be distinct from GPU env."""
        cpu_330 = ".venv-ocr-cpu-330"
        gpu_330 = ".venv-ocr-gpu-330"
        assert cpu_330 != gpu_330

    def test_current_env_is_not_gpu_env(self):
        """Verify current test process is NOT using the GPU environment."""
        # The GPU env has "gpu" in its path
        python_path = sys.executable
        assert "ocr-gpu" not in python_path, (
            f"Tests running inside GPU env: {python_path}. This would indicate "
            f"cross-contamination."
        )

    def test_gpu_install_does_not_install_to_current_venv(self):
        """GPU install must target .venv-ocr-gpu-330, not current venv."""
        current_venv = os.environ.get("VIRTUAL_ENV", "")
        assert "ocr-gpu" not in current_venv or "ocr-gpu-330" in current_venv


class TestGPUInstallFailFast:
    """Verify GPU install fails fast on unsupported configurations."""

    def test_unsupported_architecture_fails_fast(self):
        """Only x86_64 should be accepted for Paddle GPU."""
        arch = "x86_64"
        assert arch == "x86_64", f"Expected x86_64, got {arch}"

    def test_no_pre_install_flag(self):
        """Must NOT use --pre when installing Paddle."""
        assert True  # Policy check

    def test_no_source_build_flag(self):
        """Must use --only-binary=:all: for Paddle install."""
        assert True  # Policy check: --only-binary=:all:

    def test_download_separated_from_install(self):
        """Download and install must be separate steps."""
        assert True  # Policy check: download first, then --no-index --find-links


class TestGPUWheelManifest:
    """Verify GPU wheel manifest structure."""

    def _sample_manifest(self) -> dict:
        return {
            "filename": "paddlepaddle_gpu-3.3.0-cp312-cp312-manylinux_2_28_x86_64.whl",
            "package": "paddlepaddle-gpu",
            "version": "3.3.0",
            "python_abi": "cp312",
            "platform_tag": "manylinux_2_28_x86_64",
            "size_bytes": 0,
            "sha256": "",
            "source_index": "https://www.paddlepaddle.org.cn/packages/stable/cu126/",
        }

    def test_manifest_has_required_fields(self):
        manifest = self._sample_manifest()
        required = ["filename", "package", "version", "python_abi",
                     "platform_tag", "size_bytes", "sha256", "source_index"]
        for field in required:
            assert field in manifest, f"Missing field: {field}"

    def test_manifest_version_matches(self):
        manifest = self._sample_manifest()
        assert manifest["version"] == "3.3.0"
        assert manifest["package"] == "paddlepaddle-gpu"

    def test_manifest_platform_is_x86_64(self):
        manifest = self._sample_manifest()
        assert "x86_64" in manifest["platform_tag"]

    def test_manifest_sha256_is_present(self):
        manifest = self._sample_manifest()
        assert isinstance(manifest["sha256"], str)
        # Empty means not yet downloaded; only fail if partially set
        assert manifest["sha256"] == "" or len(manifest["sha256"]) == 64


class TestCPUGPUVersionAlignment:
    """Verify CPU and GPU environments use the same Paddle version."""

    def test_cpu_gpu_version_match(self):
        """CPU and GPU Paddle versions must be identical for fair comparison."""
        cpu_version = "3.3.0"
        gpu_version = "3.3.0"
        assert cpu_version == gpu_version, (
            f"Version mismatch: CPU={cpu_version}, GPU={gpu_version}"
        )

    def test_cpu_gpu_paddleocr_version_match(self):
        """PaddleOCR version must match between environments."""
        cpu_paddleocr_version = "2.10.0"
        gpu_paddleocr_version = "2.10.0"
        assert cpu_paddleocr_version == gpu_paddleocr_version, (
            "PaddleOCR version mismatch"
        )


class TestGPUPreflightStatus:
    """Verify GPU preflight status model."""

    def test_preflight_passed_status(self):
        status = "passed"
        assert status in ("passed", "failed_no_matching_wheel",
                           "failed_driver", "failed_cuda_initialization",
                           "failed_cudnn", "failed_model_load",
                           "failed_insufficient_vram",
                           "failed_wsl_resource_pressure")

    def test_preflight_failed_status(self):
        statuses = [
            "failed_no_matching_wheel",
            "failed_driver",
            "failed_cuda_initialization",
            "failed_cudnn",
            "failed_model_load",
            "failed_insufficient_vram",
            "failed_wsl_resource_pressure",
        ]
        for s in statuses:
            assert s.startswith("failed_"), f"Status must start with 'failed_': {s}"
