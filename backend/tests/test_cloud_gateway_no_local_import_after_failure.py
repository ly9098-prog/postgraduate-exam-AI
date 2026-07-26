"""Sprint 4C: Cloud gateway must NOT fall back to local adapters after failures.

In cloud_api profile, the forbidden fallback list must include local-only
backends (paddleocr, rule_fallback) but NOT remote adapters (paddleocr-vl).
"""

from __future__ import annotations

from app.core.deployment_profile import DeploymentProfile


class TestCloudGatewayNoLocalImportAfterFailure:
    """Verify cloud_api profile enforces remote-only fallback policy."""

    def test_cloud_fallback_chain_is_filtered(self):
        """_get_forbidden_fallback includes 'paddleocr' but not 'paddleocr-vl'."""
        from app.features.ocr_adapter import AdapterRegistry
        from app.features.ocr_gateway import OCRGateway

        registry = AdapterRegistry()
        gw = OCRGateway(registry=registry, mode="shadow", profile=DeploymentProfile.CLOUD_API)

        forbidden = gw._get_forbidden_fallback()

        assert "paddleocr" in forbidden, (
            f"cloud_api must forbid local 'paddleocr'. Forbidden: {forbidden}"
        )
        assert "rule_fallback" in forbidden, (
            f"cloud_api must forbid 'rule_fallback'. Forbidden: {forbidden}"
        )
        assert "paddleocr-vl" not in forbidden, (
            f"cloud_api must NOT forbid remote 'paddleocr-vl'. Forbidden: {forbidden}"
        )

    def test_cloud_no_local_after_failure_construction(self):
        """OCRGateway construction works for cloud_api profile."""
        from app.features.ocr_adapter import AdapterRegistry
        from app.features.ocr_gateway import OCRGateway

        registry = AdapterRegistry()
        gw = OCRGateway(registry=registry, mode="shadow", profile=DeploymentProfile.CLOUD_API)

        assert gw is not None
        assert gw._profile == "cloud_api"

    def test_enforce_fallback_policy_filters_local(self):
        """_enforce_fallback_policy removes forbidden backends from chain."""
        from app.features.ocr_adapter import AdapterRegistry
        from app.features.ocr_gateway import OCRGateway

        registry = AdapterRegistry()
        gw = OCRGateway(registry=registry, mode="shadow", profile=DeploymentProfile.CLOUD_API)

        chain_with_local = ["paddleocr-vl", "paddleocr", "rule_fallback"]
        filtered = gw._enforce_fallback_policy(chain_with_local)

        assert "paddleocr-vl" in filtered, "Remote adapter must survive"
        assert "paddleocr" not in filtered, "Local paddleocr must be removed"
        assert "rule_fallback" not in filtered, "rule_fallback must be removed"
        assert len(filtered) >= 1, "Must have at least one fallback"

    def test_local_profile_allows_local_backends(self):
        """local_import's _get_forbidden_fallback returns empty list."""
        from app.features.ocr_adapter import AdapterRegistry
        from app.features.ocr_gateway import OCRGateway

        registry = AdapterRegistry()
        gw = OCRGateway(registry=registry, mode="shadow", profile="local_import")

        forbidden = gw._get_forbidden_fallback()
        assert forbidden == [], (
            f"local_import must have no forbidden fallbacks. Got: {forbidden}"
        )

    def test_enforce_fallback_policy_noop_for_local(self):
        """_enforce_fallback_policy is a no-op for local_import."""
        from app.features.ocr_adapter import AdapterRegistry
        from app.features.ocr_gateway import OCRGateway

        registry = AdapterRegistry()
        gw = OCRGateway(registry=registry, mode="shadow", profile="local_import")

        chain = ["paddleocr", "paddleocr-vl", "rule_fallback"]
        filtered = gw._enforce_fallback_policy(chain)
        assert filtered == chain, (
            f"local_import should not filter. Got: {filtered}"
        )

    def test_cloud_fallback_always_has_review(self):
        """Even if all backends forbidden, chain includes 'review'."""
        from app.features.ocr_adapter import AdapterRegistry
        from app.features.ocr_gateway import OCRGateway

        registry = AdapterRegistry()
        gw = OCRGateway(registry=registry, mode="shadow", profile=DeploymentProfile.CLOUD_API)

        filtered = gw._enforce_fallback_policy(["paddleocr", "rule_fallback"])
        assert filtered == ["review"], (
            f"Should fallback to ['review']. Got: {filtered}"
        )

    def test_ocr_request_importable(self):
        """OCRRequest is importable."""
        from app.core.ocr_request import OCRRequest
        assert OCRRequest is not None

    def test_rendered_page_importable(self):
        """RenderedPage is importable."""
        from app.features.page_stream import RenderedPage
        assert RenderedPage is not None

    def test_module_result_importable(self):
        """ModuleResult and ModuleError are importable."""
        from app.core.module_result import ModuleError, ModuleResult
        assert ModuleResult is not None
        assert ModuleError is not None
