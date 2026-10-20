"""Assemble OCR resources while preserving ownership after partial startup."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

    from app.features.ocr_gateway import OCRGateway

logger = logging.getLogger("postgraduate-ai")


@dataclass
class HttpOcrResources:
    gateway: OCRGateway | None = None
    shared_http_client: httpx.AsyncClient | None = None


def initialize_http_ocr_gateway(resources: HttpOcrResources, role: str) -> None:
    import httpx

    from app.core.ocr_runtime_config import get_runtime_config
    from app.features.ocr_gateway import OCRGateway
    from app.services.ocr_worker_client import create_ocr_worker_client

    cfg = get_runtime_config()
    if cfg.enabled:
        resources.shared_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=cfg.remote_connect_timeout_sec,
                read=cfg.remote_read_timeout_sec,
                write=cfg.remote_connect_timeout_sec,
                pool=cfg.remote_connect_timeout_sec,
            ),
            limits=httpx.Limits(
                max_keepalive_connections=cfg.remote_max_concurrency,
                max_connections=cfg.remote_max_concurrency,
            ),
        )
        worker_client = create_ocr_worker_client(
            cfg,
            http_client=resources.shared_http_client,
        )
        from app.core.deployment_profile import detect_deployment_profile

        resources.gateway = OCRGateway(
            mode="gateway",
            profile=detect_deployment_profile(),
            worker_client=worker_client,
        )
        from app.services.ocr_service import set_gateway

        set_gateway(resources.gateway)
        logger.info(
            "OCR Gateway initialized (role=%s mode=gateway exec_backend=%s profile=%s env=%s)",
            role, cfg.execution_backend, cfg.profile, cfg.environment,
        )
    else:
        logger.info("OCR not enabled, skipping Gateway initialization")
