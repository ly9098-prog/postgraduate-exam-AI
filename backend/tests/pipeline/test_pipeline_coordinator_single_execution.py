"""Single coordinator execution tests — CoordinatorPipeline flow, cloud routing."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.features.coordinator_orchestrator import CoordinatorPipeline


class TestCoordinatorPipelineFlow:
    """Tests for CoordinatorPipeline creation and execution flow."""

    def test_coordinator_pipeline_created(self):
        """CoordinatorPipeline() can be instantiated."""
        pipeline = CoordinatorPipeline()
        assert pipeline is not None
        assert pipeline.profile in ("local_import", "cloud_api")

    def test_coordinator_pipeline_profile_default(self):
        """Default profile is local_import when no context is provided."""
        pipeline = CoordinatorPipeline()
        assert pipeline.profile == "local_import"
        assert pipeline.is_cloud is False

    @pytest.mark.asyncio
    async def test_coordinator_pipeline_flow_no_crash(self):
        """run_all with empty source does not crash (returns clean error)."""
        pipeline = CoordinatorPipeline()
        result = await pipeline.run_all(b"", filename="test.pdf", mime="application/pdf")
        assert result is not None
        assert isinstance(result, dict)
        assert "status" in result
        assert "stages" in result
        # Empty/invalid source should fail at input stage, not crash
        assert "input" in (result.get("stages") or {})
        # Pipeline should report a status (success or failure, not an exception)
        assert result["status"] in (
            "success", "input_failed", "page_stream_failed",
        )

    @pytest.mark.asyncio
    async def test_coordinator_pipeline_flow_has_latency(self):
        """run_all result includes total_latency_ms."""
        pipeline = CoordinatorPipeline()
        result = await pipeline.run_all(b"", filename="test.pdf")
        assert "total_latency_ms" in result
        assert isinstance(result["total_latency_ms"], (int, float))
        assert result["total_latency_ms"] >= 0


class TestCoordinatorPipelineCloudRouting:
    """Tests for cloud routing behavior."""

    def test_coordinator_pipeline_cloud_routing(self):
        """CoordinatorPipeline with cloud_api context has is_cloud=True."""
        mock_context = Mock()
        mock_context.deployment_profile = "cloud_api"

        pipeline = CoordinatorPipeline(context=mock_context)
        assert pipeline.is_cloud is True
        assert pipeline.profile == "cloud_api"

    def test_coordinator_pipeline_local_routing(self):
        """CoordinatorPipeline with local_import context has is_cloud=False."""
        mock_context = Mock()
        mock_context.deployment_profile = "local_import"

        pipeline = CoordinatorPipeline(context=mock_context)
        assert pipeline.is_cloud is False
        assert pipeline.profile == "local_import"

    def test_coordinator_pipeline_profile_from_context(self):
        """Profile is read from context.deployment_profile."""
        for profile_value, expected_cloud in [
            ("local_import", False),
            ("cloud_api", True),
        ]:
            mock_context = Mock()
            mock_context.deployment_profile = profile_value
            pipeline = CoordinatorPipeline(context=mock_context)
            assert pipeline.profile == profile_value
            assert pipeline.is_cloud == expected_cloud
