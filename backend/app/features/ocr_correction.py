"""AI OCR Correction Layer — backward-compatibility re-exports.

The shared detection/filter functions live in ocr_correction_common.py.
The AI correction logic was migrated to ocr_fix/router.py (strategy pattern
with Qwen→DeepSeek→rule fallback chain).

This module remains for backward-compatible imports only.
"""

from app.features.ocr_correction_common import (  # noqa: F401
    TIER_HIGH_THRESHOLD,
    TIER_MEDIUM_THRESHOLD,
    _classify_quality_tier,
    _detect_noise,
    _detect_structure_abnormal,
    _filter_sensitive,
    _should_correct,
)
from app.features.token_budget import (  # noqa: F401
    _reset_counters_if_needed,
    _token_usage,
)

__all__ = [
    "TIER_HIGH_THRESHOLD",
    "TIER_MEDIUM_THRESHOLD",
    "_classify_quality_tier",
    "_detect_noise",
    "_detect_structure_abnormal",
    "_filter_sensitive",
    "_should_correct",
    "_reset_counters_if_needed",
    "_token_usage",
    "correct_ocr_blocks",
]


async def correct_ocr_blocks(
    blocks: list[dict],
    config: dict | None = None,
) -> dict:
    """Backward-compat wrapper — delegates to OCRFixRouter.

    **DEPRECATED**: Prefer using OCRFixRouter directly via
    _run_ocr_correction_router in pipeline_orchestrator.py.

    The wrapper maps the legacy block-based API to the new router
    interface and returns results in the old stats format.
    """
    import asyncio
    import logging

    from app.features.ocr_correction_common import (
        _detect_noise,
        _detect_structure_abnormal,
        _should_correct,
    )
    from app.features.ocr_fix import OCRFixRouter
    from app.features.ocr_fix.interfaces import OCRFixResult
    from app.features.token_budget import check_token_limit, estimate_tokens

    logger = logging.getLogger(__name__)
    cfg = dict(config or {})

    if not cfg.get("enabled", True):
        return {
            "corrected_blocks": list(blocks),
            "stats": {"corrected_blocks": 0, "total_blocks": len(blocks)},
            "skipped_reason": "disabled",
        }

    # Check AI availability (delegates to router which handles fallbacks)
    try:
        from app.ai.client import deepseek
        ai_available = deepseek.is_available()
    except Exception:
        ai_available = False

    if not ai_available:
        return {
            "corrected_blocks": list(blocks),
            "stats": {"corrected_blocks": 0, "total_blocks": len(blocks)},
            "skipped_reason": "ai_unavailable",
        }

    router = OCRFixRouter()
    router.configure(cfg)
    corrected_blocks: list[dict] = [None] * len(blocks)
    stats = {"corrected_blocks": 0, "total_blocks": len(blocks)}

    sem = asyncio.Semaphore(3)

    async def _fix_one(idx: int, block: dict, text: str):
        async with sem:
            estimated = estimate_tokens(text) * 3
            if not await check_token_limit(estimated, cfg):
                return idx, OCRFixResult(
                    fixed_text=text,
                    model_used="skipped_budget",
                    raw_response="token_limit",
                )

            result = await router.fix(
                image=None,
                ocr_text=text,
                context={"block_index": idx, "page": block.get("page", 1)},
            )
            return idx, result

    to_correct: list[tuple[int, dict, str]] = []
    for idx, block in enumerate(blocks):
        text = str(block.get("normalized_text") or "")
        if not text.strip():
            corrected_blocks[idx] = block
            continue

        noise_score = _detect_noise(block)
        structure_score = _detect_structure_abnormal(text)
        should = _should_correct(noise_score, cfg, structure_score=structure_score)

        if not should:
            corrected_blocks[idx] = block
            continue

        to_correct.append((idx, block, text))

    fix_results = await asyncio.gather(
        *[_fix_one(idx, block, text) for idx, block, text in to_correct],
        return_exceptions=True,
    )

    for (idx, block, text), fix_result in zip(to_correct, fix_results):
        if isinstance(fix_result, BaseException):
            corrected_blocks[idx] = block
            continue

        _, result = fix_result
        new_block = dict(block)
        if result.fixed_text != text and result.confidence and result.confidence > 0:
            # Safety gate
            from app.features.ai_safety import evaluate_and_trace

            safety_trace, safe_text = evaluate_and_trace(
                stage="ocr_fix",
                model=result.model_used,
                before=text,
                after=result.fixed_text,
                context={"has_options": bool("A." in text or "A、" in text)},
            )

            if safety_trace.accepted:
                new_block["normalized_text"] = safe_text
                new_block["ocr_correction_applied"] = True
                new_block["ocr_fix_model"] = result.model_used
                stats["corrected_blocks"] += 1
            else:
                logger.warning(
                    "ocr_correction safety rejected block %d: %s",
                    idx, safety_trace.rollback_reason,
                )

        corrected_blocks[idx] = new_block

    for idx, b in enumerate(corrected_blocks):
        if b is None:
            corrected_blocks[idx] = blocks[idx]

    return {
        "corrected_blocks": [b for b in corrected_blocks if b is not None],
        "stats": stats,
    }
