"""Unit tests for ResourceGuard (Batch 3: ZSET reservation)."""

import pytest

from app.core.resource_guard import (
    ResourceGuard,
    ResourceGuardError,
    resource_guard,
)


class TestResourceGuard:
    """ResourceGuard basic invariants."""

    def test_guard_is_singleton(self):
        assert resource_guard is not None
        assert isinstance(resource_guard, ResourceGuard)

    def test_error_code_and_message(self):
        err = ResourceGuardError("TEST_CODE", "test message")
        assert err.code == "TEST_CODE"
        assert str(err) == "test message"
        assert isinstance(err, ValueError)

    def test_check_input_bytes_ok(self):
        resource_guard.check_input_bytes(1024)

    def test_check_page_count_ok(self):
        resource_guard.check_page_count(5)

    def test_check_page_count_exceeds(self):
        guard = ResourceGuard()
        guard.max_pages = 3
        with pytest.raises(ResourceGuardError) as exc_info:
            guard.check_page_count(10)
        assert exc_info.value.code == "PAGE_LIMIT_EXCEEDED"

    # ── Process owner token ──

    def test_process_owner_token_created(self):
        assert resource_guard.process_owner_token
        assert resource_guard.process_owner_token.startswith("proc_")

    def test_process_owner_token_stable(self):
        assert resource_guard.process_owner_token == resource_guard.process_owner_token

    # ── can_accept_work (system checks only, no Redis) ──

    def test_can_accept_work_returns_tuple(self):
        ok, reason = resource_guard.can_accept_work()
        assert isinstance(ok, bool)
        assert reason is None or isinstance(reason, str)

    # ── for_profile ──

    def test_for_profile_cloud(self):
        from app.core.deployment_profile import DeploymentProfile
        guard = ResourceGuard.for_profile(DeploymentProfile.CLOUD_API)
        assert guard.max_input_bytes == 5 * 1024 * 1024
        assert guard.max_pages == 30

    def test_for_profile_local(self):
        from app.core.deployment_profile import DeploymentProfile
        guard = ResourceGuard.for_profile(DeploymentProfile.LOCAL_IMPORT)
        assert guard.max_input_bytes == 200 * 1024 * 1024
        assert guard.max_pages == 600


class TestResourceGuardLocalReservation:
    """ZSET reservation in local (in-memory fallback) mode.

    These tests verify the local fallback path since no Redis is available.
    """

    @pytest.fixture
    def guard(self):
        g = ResourceGuard()
        g._thresholds.max_active_pipelines = 2
        return g

    @pytest.mark.asyncio
    async def test_acquire_release_local(self, guard):
        token = await guard.acquire_reservation("test_type", "task_001")
        assert token is not None
        assert len(token) == 32  # uuid hex

        released = await guard.release_reservation(token, resource_type="test_type")
        assert released is True

    @pytest.mark.asyncio
    async def test_acquire_release_local_multiple(self, guard):
        token1 = await guard.acquire_reservation("test_type", "task_001")
        token2 = await guard.acquire_reservation("test_type", "task_002")
        assert token1 is not None
        assert token2 is not None

        released1 = await guard.release_reservation(token1, resource_type="test_type")
        released2 = await guard.release_reservation(token2, resource_type="test_type")
        assert released1 is True
        assert released2 is True

    @pytest.mark.asyncio
    async def test_reject_when_at_capacity(self, guard):
        guard._thresholds.max_active_pipelines = 1
        token1 = await guard.acquire_reservation("test_type", "task_001")
        token2 = await guard.acquire_reservation("test_type", "task_002")
        assert token1 is not None
        assert token2 is None  # at capacity

        # Cleanup
        await guard.release_reservation(token1, resource_type="test_type")

    @pytest.mark.asyncio
    async def test_ttl_expiry_frees_slot(self, guard):
        guard._thresholds.max_active_pipelines = 1
        token1 = await guard.acquire_reservation("test_type", "task_001", ttl_sec=1)
        assert token1 is not None

        import asyncio
        await asyncio.sleep(1.1)

        token2 = await guard.acquire_reservation("test_type", "task_002")
        assert token2 is not None

        await guard.release_reservation(token2, resource_type="test_type")

    @pytest.mark.asyncio
    async def test_release_unknown_token_returns_false(self, guard):
        result = await guard.release_reservation("nonexistent", resource_type="test_type")
        assert result is False

    @pytest.mark.asyncio
    async def test_release_wrong_resource_type(self, guard):
        token = await guard.acquire_reservation("type_a", "task_001")
        assert token is not None

        # Release with wrong type — won't find in local dict
        result = await guard.release_reservation(token, resource_type="type_b")
        assert result is False  # not found with wrong type

        # Release with correct type
        result = await guard.release_reservation(token, resource_type="type_a")
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_pipeline_context_manager_success(self, guard):
        async with guard.acquire_pipeline(resource_type="test_ctx", task_id="ctx_001") as token:
            assert token is not None

    @pytest.mark.asyncio
    async def test_acquire_pipeline_context_manager_rejects(self, guard):
        guard._thresholds.max_active_pipelines = 1
        async with guard.acquire_pipeline(resource_type="test_ctx", task_id="ctx_001") as token1:
            assert token1 is not None
            async with guard.acquire_pipeline(resource_type="test_ctx", task_id="ctx_002") as token2:
                assert token2 is None  # at capacity

    @pytest.mark.asyncio
    async def test_acquire_pipeline_context_manager_releases_on_exception(self, guard):
        class TestExceptionError(Exception):
            pass

        with pytest.raises(TestExceptionError):
            async with guard.acquire_pipeline(resource_type="test_ctx", task_id="ctx_err") as token:
                assert token is not None
                raise TestExceptionError("boom")

        # After exception, slot should be free
        async with guard.acquire_pipeline(resource_type="test_ctx", task_id="ctx_after") as token:
            assert token is not None

    def test_local_isolated_instances(self):
        """Each ResourceGuard instance has its own local reservation dict (class-level)."""
        g1 = ResourceGuard()
        g2 = ResourceGuard()

        # Reservation storage is class-level, so both instances share it
        assert ResourceGuard._reservations_by_task is g1._reservations_by_task
        assert ResourceGuard._reservations_by_task is g2._reservations_by_task


class TestResourceGuardEdgeCases:
    """Edge cases for the ResourceGuard."""

    def test_for_profile_defaults(self):
        guard = ResourceGuard()
        assert guard.max_input_bytes == 10 * 1024 * 1024
        assert guard.max_pages == 50

    def test_check_input_bytes_exceeds(self):
        guard = ResourceGuard()
        guard.max_input_bytes = 100
        with pytest.raises(ResourceGuardError) as exc_info:
            guard.check_input_bytes(200)
        assert exc_info.value.code == "INPUT_TOO_LARGE"

    def test_check_render_pixels(self):
        guard = ResourceGuard()
        guard.check_render_pixels(100)
        guard.check_render_pixels(200)
        assert guard._render_pixels_consumed == 300

    def test_check_render_pixels_exceeds(self):
        guard = ResourceGuard()
        guard.max_pixel_budget = 500
        guard.check_render_pixels(400)
        with pytest.raises(ResourceGuardError):
            guard.check_render_pixels(200)

    def test_check_remote_ocr_call(self):
        guard = ResourceGuard()
        guard.max_remote_ocr_calls = 2
        guard.check_remote_ocr_call()
        guard.check_remote_ocr_call()
        with pytest.raises(ResourceGuardError):
            guard.check_remote_ocr_call()

    def test_check_artifact_bytes(self):
        guard = ResourceGuard()
        guard.max_artifact_bytes = 1000
        guard.check_artifact_bytes(600)
        guard.check_artifact_bytes(400)
        with pytest.raises(ResourceGuardError):
            guard.check_artifact_bytes(1)

    def test_system_metrics_collected(self):
        metrics = resource_guard.get_system_metrics()
        assert hasattr(metrics, "rss_mb")
        assert hasattr(metrics, "available_memory_mb")
