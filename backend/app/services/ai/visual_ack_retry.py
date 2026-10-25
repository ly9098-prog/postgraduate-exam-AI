"""Same-model acknowledgement retry for visual error analysis."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Any

from app.ai.prompts import build_visual_evidence_probe
from app.services.ai.visual_cache import _visual_evidence_is_valid

logger = logging.getLogger(__name__)

ACK_MAX_TOKENS = 160
ACK_TIMEOUT_SECONDS = 8
ACK_MAIN_BUDGET_MS = 38_000
Chat = Callable[..., Awaitable[dict]]


@dataclass(slots=True)
class VisualAckResult:
    evidence: str
    retried: bool
    retry_ms: int
    tokens_used_delta: int


def should_retry_visual_ack(
    *, parsed_valid: bool, grounding_valid: bool, duration_ms: int
) -> bool:
    return (
        parsed_valid
        and grounding_valid
        and duration_ms <= ACK_MAIN_BUDGET_MS
    )


async def retry_visual_ack(
    image_data_urls: list[str],
    *,
    runtime: Any,
    source_model: str,
    wrong_question_id: int,
    current_evidence: str,
    chat: Chat,
    extract_evidence: Callable[[str], str],
) -> VisualAckResult:
    """Run one bounded acknowledgement probe with the already-selected model."""
    try:
        async with asyncio.timeout(ACK_TIMEOUT_SECONDS + 1):
            probe = await chat(
                build_visual_evidence_probe(image_data_urls),
                temperature=0.0,
                model=runtime.model_name,
                api_key=runtime.api_key,
                base_url=runtime.base_url,
                provider=runtime.provider,
                timeout=ACK_TIMEOUT_SECONDS,
                max_tokens=ACK_MAX_TOKENS,
                prefer_direct_answer=True,
            )
        recovered = extract_evidence(probe.get("content", ""))
        retry_ms = int(probe.get("duration_ms") or 0)
        tokens = int(probe.get("tokens_used") or 0)
        if _visual_evidence_is_valid(recovered):
            logger.info(
                "ai.error_analysis.visual_ack_recovered wq_id=%s model=%s "
                "retry_ms=%s evidence=%r",
                wrong_question_id,
                source_model,
                retry_ms,
                recovered[:120],
            )
        return VisualAckResult(recovered, True, retry_ms, tokens)
    except Exception as exc:
        logger.warning(
            "ai.error_analysis.visual_ack_retry_failed wq_id=%s model=%s err=%s",
            wrong_question_id,
            source_model,
            type(exc).__name__,
        )
        return VisualAckResult(current_evidence, True, 0, 0)
