"""Sprint 4B — ResourceGuard tests for dual-environment profiles."""

from __future__ import annotations

import pytest

from app.core.deployment_profile import DeploymentProfile
from app.features.resource_guard import (
    ARTIFACT_SIZE_LIMIT_EXCEEDED,
    CONCURRENCY_LIMIT_EXCEEDED,
    INPUT_TOO_LARGE,
    PAGE_LIMIT_EXCEEDED,
    PAGE_TIMEOUT,
    PIPELINE_TIMEOUT,
    PIXEL_BUDGET_EXCEEDED,
    REMOTE_OCR_CALL_BUDGET_EXCEEDED,
    ResourceGuard,
    ResourceGuardError,
)

MB = 1024 * 1024


class TestGuardCloudDefaults:
    def test_guard_cloud_defaults(self) -> None:
        guard = ResourceGuard.for_profile(DeploymentProfile.CLOUD_API)
        assert guard.max_input_bytes == 5 * MB
        assert guard.max_pages == 30
        assert guard.max_remote_ocr_calls == 60
        assert guard.max_artifact_bytes == 50 * MB
        assert guard.max_pipeline_seconds == 1800
        assert guard.max_page_seconds == 120
        assert guard.max_concurrent_documents == 1
        assert guard.max_concurrent_pages == 1


class TestGuardLocalDefaults:
    def test_guard_local_defaults(self) -> None:
        guard = ResourceGuard.for_profile(DeploymentProfile.LOCAL_IMPORT)
        assert guard.max_input_bytes == 200 * MB
        assert guard.max_pages == 600
        assert guard.max_remote_ocr_calls == 500
        assert guard.max_artifact_bytes == 500 * MB
        assert guard.max_pipeline_seconds == 7200
        assert guard.max_page_seconds == 600
        assert guard.max_concurrent_documents == 1
        assert guard.max_concurrent_pages == 3


class TestInputBytesCheck:
    def test_check_input_bytes_accept(self) -> None:
        guard = ResourceGuard.for_profile(DeploymentProfile.CLOUD_API)
        guard.check_input_bytes(100)  # should not raise

    def test_check_input_bytes_reject(self) -> None:
        guard = ResourceGuard.for_profile(DeploymentProfile.CLOUD_API)
        huge = 200 * MB
        with pytest.raises(ResourceGuardError) as exc:
            guard.check_input_bytes(huge)
        assert exc.value.code == INPUT_TOO_LARGE


class TestPageCountCheck:
    def test_check_page_count_reject(self) -> None:
        guard = ResourceGuard.for_profile(DeploymentProfile.CLOUD_API)
        with pytest.raises(ResourceGuardError) as exc:
            guard.check_page_count(9999)
        assert exc.value.code == PAGE_LIMIT_EXCEEDED


class TestRemoteOcrCallBudget:
    def test_check_remote_ocr_call_budget(self) -> None:
        guard = ResourceGuard.for_profile(DeploymentProfile.CLOUD_API)
        # Consume all allowed calls
        for _ in range(guard.max_remote_ocr_calls):
            guard.check_remote_ocr_call()  # should not raise
        # Next call should fail
        with pytest.raises(ResourceGuardError) as exc:
            guard.check_remote_ocr_call()
        assert exc.value.code == REMOTE_OCR_CALL_BUDGET_EXCEEDED


class TestConcurrentDocumentLimit:
    @pytest.mark.asyncio
    async def test_concurrent_document_limit(self) -> None:
        guard = ResourceGuard.for_profile(DeploymentProfile.CLOUD_API)
        assert guard.max_concurrent_documents == 1

        # First reservation should succeed (local fallback without Redis)
        token = await guard.acquire_reservation(
            resource_type="test_document",
            task_id="test-task-1",
        )
        assert token is not None

        # Second reservation should fail — capacity reached
        token2 = await guard.acquire_reservation(
            resource_type="test_document",
            task_id="test-task-2",
        )
        assert token2 is None

        # Release and verify
        ok = await guard.release_reservation(token, resource_type="test_document")
        assert ok is True


class TestErrorCodeValues:
    def test_error_code_values(self) -> None:
        assert INPUT_TOO_LARGE == "INPUT_TOO_LARGE"
        assert PAGE_LIMIT_EXCEEDED == "PAGE_LIMIT_EXCEEDED"
        assert PIXEL_BUDGET_EXCEEDED == "PIXEL_BUDGET_EXCEEDED"
        assert CONCURRENCY_LIMIT_EXCEEDED == "CONCURRENCY_LIMIT_EXCEEDED"
        assert REMOTE_OCR_CALL_BUDGET_EXCEEDED == "REMOTE_OCR_CALL_BUDGET_EXCEEDED"
        assert ARTIFACT_SIZE_LIMIT_EXCEEDED == "ARTIFACT_SIZE_LIMIT_EXCEEDED"
        assert PIPELINE_TIMEOUT == "PIPELINE_TIMEOUT"
        assert PAGE_TIMEOUT == "PAGE_TIMEOUT"

        # Verify all are strings
        for code in [
            INPUT_TOO_LARGE,
            PAGE_LIMIT_EXCEEDED,
            PIXEL_BUDGET_EXCEEDED,
            CONCURRENCY_LIMIT_EXCEEDED,
            REMOTE_OCR_CALL_BUDGET_EXCEEDED,
            ARTIFACT_SIZE_LIMIT_EXCEEDED,
            PIPELINE_TIMEOUT,
            PAGE_TIMEOUT,
        ]:
            assert isinstance(code, str)
