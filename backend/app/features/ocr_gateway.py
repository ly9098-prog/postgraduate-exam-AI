"""OCR Gateway — Production OCR routing entry point.

Reuses existing:
- OcrAdapter (protocol)
- OCRRequest
- AdapterRegistry
- AdapterSelector
- ModuleResult

OCR_GATEWAY_MODE:
  legacy  — existing path (default)
  shadow  — compute routing + conversion, compare but don't call backend
  gateway — production entry, routes through Gateway

Rules:
- Route by capability, not by backend name (no if/elif on backend names)
- Unified timeout/retry/fallback
- Never call the same page's OCR twice in shadow mode
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.deployment_profile import DeploymentProfile
from app.core.module_result import ModuleError, ModuleResult
from app.core.ocr_request import OCRRequest
from app.core.ocr_types import STABLE_ERROR_CODES, WorkerResult
from app.features.ocr_adapter import AdapterRegistry, AdapterSelector
from app.features.page_stream import RenderedPage

logger = logging.getLogger(__name__)

_OCR_GATEWAY_MODE = os.environ.get("OCR_GATEWAY_MODE", "legacy")

# Default timeout per OCR call (seconds)
_OCR_TIMEOUT_SECONDS = 120

# Backend preference order (used when capabilities are equal)
_PREFERRED_BACKENDS = ["paddleocr", "paddleocr-vl", "rule_fallback"]


# ---------------------------------------------------------------------------
# Required capabilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RequiredOCRCapabilities:
    """Capabilities required for a specific OCR recognition request."""
    text: bool = True
    bbox: bool = True
    layout: bool = False
    formula: bool = False
    code: bool = False
    offline: bool = False


# ---------------------------------------------------------------------------
# Gateway routing result (for shadow mode comparison)
# ---------------------------------------------------------------------------


@dataclass
class GatewayRouteDecision:
    """The routing decision the Gateway would make (shadow mode)."""
    selected_backend: str = ""
    confidence: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    capabilities_met: bool = False
    fallback_chain: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OCRGateway
# ---------------------------------------------------------------------------


class OCRGateway:
    """Production OCR routing entry point.

    ``recognize_page`` is the primary API. All Page-level OCR goes through
    this Gateway, never directly to an adapter.

    In shadow mode, the Gateway computes what it *would* do but does not
    call any backend. The caller runs the legacy path as usual.

    Profile-aware routing:
    - local_import: LOCAL_PADDLE_FULL → LOCAL_PADDLE_CPU → REMOTE_LIGHTWEIGHT → REVIEW
    - cloud_api: REMOTE_LIGHTWEIGHT → REVIEW (never LOCAL_PADDLE)
    """

    def __init__(
        self,
        registry: AdapterRegistry | None = None,
        selector: AdapterSelector | None = None,
        mode: str = "",
        *,
        profile: DeploymentProfile,
        capabilities: dict | None = None,
        # Remote adapter config (from DB resolution, Sprint 4D)
        vl_api_token: str = "",
        vl_base_url: str = "",
        vl_model: str = "PaddleOCR-VL-1.6",
        # Local worker client (optional, lazy-init if not provided)
        worker_client: Any = None,
    ) -> None:
        self._mode = mode or _OCR_GATEWAY_MODE
        self._profile = profile
        self._registry = registry or AdapterRegistry()
        self._selector = selector or AdapterSelector(self._registry)

        # Sprint 4D: store resolved remote adapter config
        self._vl_api_token = vl_api_token
        self._vl_base_url = vl_base_url
        self._vl_model = vl_model

        # Local worker client for process-isolated OCR
        self._worker_client = worker_client

        # Register backends according to profile
        self._register_profile_backends(capabilities)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_shadow(self) -> bool:
        return self._mode == "shadow"

    @property
    def is_gateway(self) -> bool:
        return self._mode == "gateway"

    # ── Public API ──

    async def recognize_page(
        self,
        page: RenderedPage,
        *,
        request: OCRRequest | None = None,
        requirements: RequiredOCRCapabilities | None = None,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        """Recognize a single page through the Gateway.

        Args:
            page: The page to recognize.
            request: Optional OCRRequest (created from page if not provided).
            requirements: Required capabilities for this recognition.
            trace_id: Trace ID for logging.

        Returns:
            ModuleResult with DocumentIR data (or error).
        """
        start = time.monotonic()
        req = request or self._build_request(page)
        caps = requirements or RequiredOCRCapabilities()

        # Resolve routing
        route = self._resolve_route(req, caps)
        logger.debug(
            "OCRGateway[%s]: p%d backend=%s caps=%s",
            self._mode, page.page_index, route.selected_backend, caps,
        )

        if self.is_shadow:
            # Shadow: return route decision only, no actual OCR
            latency = round((time.monotonic() - start) * 1000, 2)
            return ModuleResult.success(
                data={"gateway_route": {
                    "selected_backend": route.selected_backend,
                    "fallback_chain": route.fallback_chain,
                    "reason_codes": route.reason_codes,
                }},
                data_type="GatewayRouteDecision",
                module_name="ocr_gateway",
                trace_id=trace_id,
                latency_ms=latency,
            )

        if not self.is_gateway:
            # Legacy mode fallback
            return ModuleResult.failure(
                ModuleError(
                    code="GATEWAY_NOT_ACTIVE",
                    message=f"OCRGateway in {self._mode} mode — use legacy path instead",
                    category="system",
                ),
                module_name="ocr_gateway",
                trace_id=trace_id,
                latency_ms=round((time.monotonic() - start) * 1000, 2),
            )

        # Gateway mode: execute through adapter with fallback chain
        return await self._execute_with_fallback(
            req, route, trace_id=trace_id,
        )

    # ── New: Business caller API ──

    async def recognize_pages(
        self,
        images: list[tuple[int, bytes]],
        *,
        requirements: RequiredOCRCapabilities | None = None,
        trace_id: str = "",
    ) -> list[WorkerResult]:
        """Page-level OCR for business callers.

        Args:
            images: ``[(page_index, png_bytes), ...]``.
            requirements: Capability requirements.
            trace_id: Trace ID for logging.

        Returns:
            List of ``WorkerResult``, sorted by ``page_index``.
            Each result is independent — a single page failure does not
            affect others.
        """
        if self.is_shadow:
            return [
                WorkerResult(
                    request_id="",
                    page_index=idx,
                    status="failed",
                    stable_error_code="GATEWAY_SHADOW",
                    error_type="Gateway in shadow mode",
                )
                for idx, _ in images
            ]

        if not self.is_gateway:
            return [
                WorkerResult(
                    request_id="",
                    page_index=idx,
                    status="failed",
                    stable_error_code="GATEWAY_NOT_ACTIVE",
                    error_type=f"OCRGateway in {self._mode} mode",
                )
                for idx, _ in images
            ]

        # Initialize worker client for gateway mode
        if self._worker_client is None:
            try:
                self._worker_client = self._init_worker_client()
            except Exception as exc:
                logger.warning("Worker client init failed: %s", exc)

        if self._worker_client is None:
            return [
                WorkerResult(
                    request_id="", page_index=idx,
                    status="failed",
                    stable_error_code=STABLE_ERROR_CODES["ENGINE_NOT_AVAILABLE"],
                    error_type="No worker client — execution backend is disabled",
                )
                for idx, _ in images
            ]

        return await self._worker_client.recognize_batch(images)

    async def shutdown(
        self,
        graceful_timeout: float = 5.0,
        kill_timeout: float = 10.0,
    ) -> None:
        """Shutdown worker pool and close adapters.

        Must be called during application lifespan shutdown.
        """
        logger.info(
            "OCRGateway shutting down (graceful=%.0fs kill=%.0fs)",
            graceful_timeout, kill_timeout,
        )
        if self._worker_client is not None:
            await self._worker_client.shutdown()
        self._registry.close_all()

    @property
    def worker_metrics(self) -> dict:
        """Return worker pool metrics (or empty dict if not started)."""
        if self._worker_client is not None:
            return self._worker_client.metrics
        return {"accepted": 0, "running": 0, "finished": 0}

    # ── Internal helpers ──

    def _get_runtime_config(self):
        """Get runtime config (lazy)."""
        from app.core.ocr_runtime_config import get_runtime_config
        return get_runtime_config()

    def _init_worker_client(self):
        """Lazy-init the appropriate worker client via the unified factory.

        The factory returns ``None`` when ``execution_backend`` is ``"disabled"``.
        """
        from app.services.ocr_worker_client import create_ocr_worker_client
        cfg = self._get_runtime_config()
        return create_ocr_worker_client(cfg)

    async def route_page(
        self,
        page: RenderedPage,
        *,
        requirements: RequiredOCRCapabilities | None = None,
    ) -> GatewayRouteDecision:
        """Only compute the route decision (no OCR). Useful for shadow comparison."""
        caps = requirements or RequiredOCRCapabilities()
        req = self._build_request(page)
        return self._resolve_route(req, caps)

    # ── Private ──

    def _resolve_route(
        self,
        request: OCRRequest,
        requirements: RequiredOCRCapabilities,
    ) -> GatewayRouteDecision:
        """Resolve the optimal backend and fallback chain."""
        reason_codes: list[str] = []
        fallback_chain: list[str] = []

        # Try selected adapter
        selected = self._selector.select_ocr(
            request,
            require_layout=requirements.layout,
            require_formula=requirements.formula,
            require_code=requirements.code,
            require_offline=requirements.offline,
        )

        if selected:
            backend = selected.capabilities.backend
            reason_codes.append(f"SELECTED:{backend}")
            fallback_chain.append(backend)
        else:
            backend = "paddleocr"
            reason_codes.append("FALLBACK_TO_DEFAULT")

        # Build fallback chain from preferred backends
        available = {a.capabilities.backend for a in self._registry.list_ocr()}
        for b in _PREFERRED_BACKENDS:
            if b not in fallback_chain and b in available:
                fallback_chain.append(b)
            if len(fallback_chain) >= 3:
                break

        # Enforce profile fallback policy
        fallback_chain = self._enforce_fallback_policy(fallback_chain)

        return GatewayRouteDecision(
            selected_backend=backend,
            confidence=0.8 if selected else 0.5,
            reason_codes=reason_codes,
            capabilities_met=selected is not None,
            fallback_chain=fallback_chain,
        )

    async def _execute_with_fallback(
        self,
        request: OCRRequest,
        route: GatewayRouteDecision,
        *,
        trace_id: str = "",
    ) -> ModuleResult[Any]:
        """Execute OCR with fallback chain."""
        start = time.monotonic()

        for backend_name in route.fallback_chain:
            adapter = self._registry.get_ocr(backend_name)
            if adapter is None:
                continue

            try:
                result = await asyncio.wait_for(
                    adapter.process(request, trace_id=trace_id),
                    timeout=_OCR_TIMEOUT_SECONDS,
                )
                if result.is_success:
                    return result

                logger.warning(
                    "OCRGateway: %s failed (recoverable=%s), trying next",
                    backend_name, result.error.recoverable if result.error else "?",
                )
            except TimeoutError:
                logger.warning("OCRGateway: %s timed out after %ds", backend_name, _OCR_TIMEOUT_SECONDS)
            except Exception as e:
                logger.warning("OCRGateway: %s error: %s", backend_name, e, exc_info=True)

        latency = round((time.monotonic() - start) * 1000, 2)
        return ModuleResult.failure(
            ModuleError(
                code="OCR_ALL_BACKENDS_FAILED",
                message=f"All OCR backends failed: {route.fallback_chain}",
                category="model",
                recoverable=False,
            ),
            module_name="ocr_gateway",
            trace_id=trace_id,
            latency_ms=latency,
        )

    def _build_request(self, page: RenderedPage) -> OCRRequest:
        """Build an OCRRequest from a RenderedPage."""
        source = b""
        if page.image_path and os.path.exists(page.image_path):
            with open(page.image_path, "rb") as f:
                source = f.read()

        return OCRRequest(
            source=source or b" ",
            source_type="png",
            filename=f"p{page.page_index:04d}.png",
        )

    def _register_profile_backends(self, capabilities: dict | None = None) -> None:
        """Register OCR backends according to deployment profile.

        local_import: full local + remote backends.
        cloud_api: remote lightweight only (never local PaddleOCR).
        """
        if self._registry.list_ocr():
            return  # already registered

        try:
            from app.features.ocr_adapter import PaddleOCRLocalAdapter

            if self._profile == DeploymentProfile.LOCAL_IMPORT:
                self._registry.register_ocr(PaddleOCRLocalAdapter(engine="paddleocr"))
                logger.info("OCRGateway[%s]: registered PaddleOCRLocalAdapter", self._profile.value)
            else:
                logger.info(
                    "OCRGateway[%s]: skipping PaddleOCRLocalAdapter (cloud profile)",
                    self._profile.value,
                )
        except Exception as e:
            logger.debug("OCRGateway: could not register local adapter: %s", e)

        # Remote lightweight adapter (both profiles)
        self._register_remote_adapter()

    def _register_remote_adapter(self) -> None:
        """Register the remote lightweight OCR adapter if available.

        Uses resolved DB config (Sprint 4D) — falls back to empty token
        which will produce a clear VL_NOT_CONFIGURED error.
        """
        try:
            from app.features.ocr_adapter import PaddleOCRVLDocumentAdapter

            self._registry.register_ocr(PaddleOCRVLDocumentAdapter(
                api_token=self._vl_api_token,
                base_url=self._vl_base_url,
                model=self._vl_model,
            ))
            logger.info(
                "OCRGateway[%s]: registered PaddleOCRVLDocumentAdapter (token=%s endpoint=%s)",
                self._profile.value,
                "present" if self._vl_api_token else "empty",
                self._vl_base_url or "default",
            )
        except ImportError:
            logger.debug("OCRGateway: PaddleOCRVLDocumentAdapter not available")
        except Exception as e:
            logger.debug("OCRGateway: could not register remote adapter: %s", e)

    def _get_forbidden_fallback(self) -> list[str]:
        """Return backends that are forbidden as fallback for the current profile."""
        if self._profile == DeploymentProfile.CLOUD_API:
            # cloud_api must never fall back to local full PaddleOCR.
            # paddleocr-vl is a REMOTE API adapter — it IS allowed.
            return ["paddleocr", "rule_fallback"]  # rule_fallback is local-only
        return []

    def _enforce_fallback_policy(self, fallback_chain: list[str]) -> list[str]:
        """Enforce profile fallback policy — filter out forbidden backends."""
        forbidden = self._get_forbidden_fallback()
        filtered = [b for b in fallback_chain if b not in forbidden]
        if filtered != fallback_chain:
            logger.warning(
                "OCRGateway[%s]: removed forbidden fallbacks %s → %s",
                self._profile.value,
                [b for b in fallback_chain if b in forbidden],
                filtered,
            )
        return filtered or ["review"]  # must have at least review
