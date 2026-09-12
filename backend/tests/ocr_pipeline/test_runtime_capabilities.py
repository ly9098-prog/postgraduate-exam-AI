"""Sprint 4B — RuntimeCapabilities tests."""

from __future__ import annotations

import dataclasses

import pytest

from app.core.deployment_profile import DeploymentProfile
from app.features.runtime_capabilities import (
    RuntimeCapabilities,
    build_runtime_capabilities,
)

GB = 1024 * 1024 * 1024


class TestLocalImportDefaults:
    def test_local_import_defaults(self) -> None:
        caps = build_runtime_capabilities(profile=DeploymentProfile.LOCAL_IMPORT)
        assert caps.local_ocr_allowed is True
        assert caps.database_sync_allowed is True
        assert caps.batch_import_allowed is True
        assert caps.page_stream_window_size == 3
        assert caps.gpu_available is True


class TestCloudApiDefaults:
    def test_cloud_api_defaults(self) -> None:
        caps = build_runtime_capabilities(profile=DeploymentProfile.CLOUD_API)
        assert caps.local_ocr_allowed is False
        assert caps.database_sync_allowed is False
        assert caps.batch_import_allowed is False
        assert caps.page_stream_window_size == 1
        assert caps.gpu_available is False


class TestSerialization:
    def test_serialization_round_trip(self) -> None:
        original = build_runtime_capabilities(profile=DeploymentProfile.LOCAL_IMPORT)
        data = original.to_dict()
        restored = RuntimeCapabilities.from_dict(data)
        assert restored.profile == original.profile
        assert restored.cpu_count == original.cpu_count
        assert restored.gpu_memory_bytes == original.gpu_memory_bytes
        assert restored.local_ocr_allowed == original.local_ocr_allowed
        assert restored.page_stream_window_size == original.page_stream_window_size


class TestFrozenDataclass:
    def test_capabilities_are_frozen(self) -> None:
        caps = build_runtime_capabilities(profile=DeploymentProfile.LOCAL_IMPORT)
        with pytest.raises(dataclasses.FrozenInstanceError):
            caps.cpu_count = 8  # type: ignore[misc]


class TestExplicitOverrides:
    def test_explicit_overrides(self) -> None:
        caps = build_runtime_capabilities(
            profile=DeploymentProfile.CLOUD_API, cpu_count=4,
        )
        assert caps.cpu_count == 4


class TestGpuMemory:
    def test_local_has_gpu_memory(self) -> None:
        caps = build_runtime_capabilities(profile=DeploymentProfile.LOCAL_IMPORT)
        assert caps.gpu_memory_bytes == 4 * GB

    def test_cloud_gpu_memory_is_none(self) -> None:
        caps = build_runtime_capabilities(profile=DeploymentProfile.CLOUD_API)
        assert caps.gpu_memory_bytes is None
