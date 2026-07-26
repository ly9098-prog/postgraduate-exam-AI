"""Tests for CoordinatorPipeline profile integration."""

from unittest.mock import Mock

import pytest

from app.features.coordinator_orchestrator import CoordinatorPipeline


class TestOrchestratorProfileIntegration:
    """CoordinatorPipeline profile-aware behaviour tests."""

    def test_coordinator_pipeline_created(self):
        """CoordinatorPipeline() creates without error."""
        pipe = CoordinatorPipeline()
        assert pipe is not None

    def test_coordinator_pipeline_profile_default(self):
        """Default profile is 'local_import' when no context supplied."""
        pipe = CoordinatorPipeline()
        assert pipe.profile == "local_import"

    def test_coordinator_pipeline_cloud_profile(self):
        """is_cloud is True when context has cloud_api profile."""
        mock_ctx = Mock(deployment_profile="cloud_api")
        pipe = CoordinatorPipeline(context=mock_ctx)
        assert pipe.is_cloud is True
        assert pipe.profile == "cloud_api"

    def test_coordinator_pipeline_local_profile(self):
        """is_cloud is False when context has local_import profile."""
        mock_ctx = Mock(deployment_profile="local_import")
        pipe = CoordinatorPipeline(context=mock_ctx)
        assert pipe.is_cloud is False
        assert pipe.profile == "local_import"

    def test_profile_with_runtime_capabilities(self):
        """Profile property respects context.runtime_capabilities for window_size etc."""
        mock_ctx = Mock(deployment_profile="local_import", runtime_capabilities={
            "page_stream_window_size": 5,
            "page_stream_overlap": 2,
        })
        pipe = CoordinatorPipeline(context=mock_ctx)
        assert pipe.profile == "local_import"

    @pytest.mark.asyncio
    async def test_run_ocr_stage_empty(self):
        """run_ocr_stage with empty pages returns empty list."""
        pipe = CoordinatorPipeline()
        results = await pipe.run_ocr_stage([])
        assert isinstance(results, list)
        assert len(results) == 0
