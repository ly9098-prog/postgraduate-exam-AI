"""Sprint 4B — Profile frozen on resume tests.

Verifies that deployment_profile and runtime_capabilities are preserved
through PipelineExecutionContext serialization round-trips.
"""

from __future__ import annotations

from app.features.control_plane import PipelineExecutionContext


class TestContextProfile:
    def test_context_contains_profile(self) -> None:
        ctx = PipelineExecutionContext(deployment_profile="cloud_api")
        assert ctx.deployment_profile == "cloud_api"

    def test_profile_in_to_dict(self) -> None:
        ctx = PipelineExecutionContext(
            pipeline_id="pl-test",
            deployment_profile="local_import",
        )
        data = ctx.to_dict()
        assert data["deployment_profile"] == "local_import"

    def test_profile_in_from_dict(self) -> None:
        data = {
            "deployment_profile": "cloud_api",
        }
        ctx = PipelineExecutionContext.from_dict(data)
        assert ctx.deployment_profile == "cloud_api"

    def test_runtime_capabilities_in_context(self) -> None:
        caps = {
            "profile": "local_import",
            "cpu_count": 16,
            "gpu_available": True,
            "local_ocr_allowed": True,
        }
        ctx = PipelineExecutionContext(
            pipeline_id="pl-caps",
            runtime_capabilities=caps,
        )
        data = ctx.to_dict()
        restored = PipelineExecutionContext.from_dict(data)
        assert restored.runtime_capabilities["profile"] == "local_import"
        assert restored.runtime_capabilities["cpu_count"] == 16
        assert restored.runtime_capabilities["gpu_available"] is True
        assert restored.runtime_capabilities["local_ocr_allowed"] is True
