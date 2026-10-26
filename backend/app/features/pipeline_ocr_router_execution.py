"""Budget-checked concurrent correction requests and usage recording."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_ocr_router_state import RouterStageState


async def request_router_fix(
    state: RouterStageState,
    idx: int,
    block: dict,
    text: str,
    *,
    ports: Callable[[str], Any],
) -> Any:
    """Read image and log the candidate immediately before its provider call."""
    page_num = block.get("page", 1)
    page_image = state.page_images.get(page_num) if state.page_images else None
    ports("logger").info(
        "【OCR-4】AI纠错输入 | block=%d page=%s noise=%.3f structure=%.3f %s",
        idx,
        page_num,
        ports("_detect_noise")(block),
        ports("_detect_structure_abnormal")(text),
        ports("safe_text_preview")(text),
    )
    has_options = ports("bool")(ports("re").search("[A-D][.、．）)\\s]", text))
    result = await state.router.fix(
        image=page_image,
        ocr_text=text,
        context={
            "block_index": idx,
            "page": page_num,
            "entry_point": "ocr_correction_router",
            "has_options": has_options,
        },
    )
    return result


async def record_router_usage(
    state: RouterStageState,
    result: Any,
    record_token_usage: Any,
    *,
    ports: Callable[[str], Any],
) -> None:
    """Record provider aggregate tokens before returning its candidate."""
    router_stats = (ports("getattr")(result, "metadata", None) or {}).get(
        "router_call_stats"
    ) or {}
    used_tokens = ports("int")(
        router_stats.get("tokens_used", result.tokens_used or 0) or 0
    )
    if used_tokens:
        await record_token_usage(used_tokens)


async def execute_router_candidates(
    state: RouterStageState, *, ports: Callable[[str], Any]
) -> None:
    """Gather all candidates with three concurrent budget/model operations."""
    from app.features.token_budget import check_token_limit, record_token_usage
    from app.features.token_budget import estimate_tokens as _est

    sem = ports("asyncio").Semaphore(3)
    from types import SimpleNamespace as _FixResult

    async def _fix_one(idx: int, block: dict, text: str):
        async with sem:
            estimated = _est(text) * 3
            if not await check_token_limit(estimated, state.router_config):
                return (
                    idx,
                    _FixResult(
                        fixed_text=text,
                        model_used="skipped_budget",
                        raw_response="token_limit",
                        confidence=None,
                        tokens_used=None,
                        duration_ms=None,
                        risk_flags=None,
                        safety=None,
                    ),
                )
            result = await request_router_fix(state, idx, block, text, ports=ports)
            await record_router_usage(state, result, record_token_usage, ports=ports)
            return (idx, result)

    state.fix_results = await ports("asyncio").gather(
        *[_fix_one(idx, block, text) for idx, block, text, _, _ in state.to_correct],
        return_exceptions=True,
    )
