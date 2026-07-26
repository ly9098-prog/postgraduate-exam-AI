"""Tests for RuntimeCapabilities profile-based defaults."""


from app.core.deployment_profile import DeploymentProfile
from app.features.runtime_capabilities import RuntimeCapabilities, build_runtime_capabilities


class TestProfileCapabilityEnforcement:
    """RuntimeCapabilities profile-aware construction tests."""

    def test_local_allows_local_ocr(self):
        """LOCAL_IMPORT profile enables local_ocr_allowed and batch features."""
        caps = RuntimeCapabilities(
            profile=DeploymentProfile.LOCAL_IMPORT,
            cpu_count=16,
            memory_limit_bytes=32_000_000_000,
            gpu_available=True,
            gpu_memory_bytes=4_000_000_000,
            local_ocr_allowed=True,
            remote_ocr_allowed=True,
            batch_import_allowed=True,
            database_sync_allowed=True,
            max_concurrent_documents=1,
            max_concurrent_pages=1,
            page_stream_window_size=3,
            page_stream_overlap=1,
            gpu_ocr_batch_size=1,
            gpu_memory_budget_bytes=3_200_000_000,
            max_rendered_page_cache=3,
            max_remote_ocr_calls_per_document=500,
        )
        assert caps.local_ocr_allowed is True
        assert caps.database_sync_allowed is True
        assert caps.batch_import_allowed is True
        assert caps.remote_ocr_allowed is True
        assert caps.gpu_available is True

    def test_cloud_denies_local_ocr(self):
        """CLOUD_API profile disables local_ocr and batch features."""
        caps = RuntimeCapabilities(
            profile=DeploymentProfile.CLOUD_API,
            cpu_count=2,
            memory_limit_bytes=2_000_000_000,
            gpu_available=False,
            gpu_memory_bytes=None,
            local_ocr_allowed=False,
            remote_ocr_allowed=True,
            batch_import_allowed=False,
            database_sync_allowed=False,
            max_concurrent_documents=1,
            max_concurrent_pages=1,
            page_stream_window_size=1,
            page_stream_overlap=0,
            gpu_ocr_batch_size=0,
            gpu_memory_budget_bytes=0,
            max_rendered_page_cache=1,
            max_remote_ocr_calls_per_document=100,
        )
        assert caps.local_ocr_allowed is False
        assert caps.database_sync_allowed is False
        assert caps.batch_import_allowed is False
        assert caps.remote_ocr_allowed is True
        assert caps.gpu_available is False

    def test_build_local_defaults(self):
        """build_runtime_capabilities returns correct default caps for LOCAL_IMPORT."""
        caps = build_runtime_capabilities(profile=DeploymentProfile.LOCAL_IMPORT)
        assert caps.profile == DeploymentProfile.LOCAL_IMPORT
        assert caps.local_ocr_allowed is True
        assert caps.database_sync_allowed is True
        assert caps.batch_import_allowed is True
        assert caps.page_stream_window_size == 3
        assert caps.page_stream_overlap == 1

    def test_build_cloud_defaults(self):
        """build_runtime_capabilities returns correct default caps for CLOUD_API."""
        caps = build_runtime_capabilities(profile=DeploymentProfile.CLOUD_API)
        assert caps.profile == DeploymentProfile.CLOUD_API
        assert caps.local_ocr_allowed is False
        assert caps.database_sync_allowed is False
        assert caps.batch_import_allowed is False
        assert caps.page_stream_window_size == 1
        assert caps.page_stream_overlap == 0

    def test_build_runtime_capabilities_with_overrides(self):
        """build_runtime_capabilities respects explicit overrides."""
        caps = build_runtime_capabilities(
            profile=DeploymentProfile.LOCAL_IMPORT,
            page_stream_window_size=5,
            max_concurrent_pages=3,
        )
        assert caps.page_stream_window_size == 5
        assert caps.max_concurrent_pages == 3
        # defaults not overridden should still hold
        assert caps.max_concurrent_documents == 1

    def test_runtime_capabilities_to_dict(self):
        """to_dict() produces valid dict with profile as string."""
        caps = build_runtime_capabilities(profile=DeploymentProfile.LOCAL_IMPORT)
        d = caps.to_dict()
        assert d["profile"] == "local_import"
        assert isinstance(d["local_ocr_allowed"], bool)
        assert isinstance(d["page_stream_window_size"], int)

    def test_runtime_capabilities_from_dict(self):
        """from_dict() reconstructs RuntimeCapabilities correctly."""
        original = build_runtime_capabilities(profile=DeploymentProfile.CLOUD_API)
        d = original.to_dict()
        reconstructed = RuntimeCapabilities.from_dict(d)
        assert reconstructed.profile == original.profile
        assert reconstructed.local_ocr_allowed == original.local_ocr_allowed
        assert reconstructed.page_stream_window_size == original.page_stream_window_size
