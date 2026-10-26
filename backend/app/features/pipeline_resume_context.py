"""Resume pipeline context with historical session and live lookup boundaries."""

from __future__ import annotations

from app.features.pipeline_resume_state import ResumeRunState


def resolve_resume_mode(state: ResumeRunState) -> None:
    """Resolve mode with the original ValueError-only fallback."""
    state.mode_str = state.opts.get("import_mode", "auto")
    try:
        state.import_mode = state.port("ImportMode")(state.mode_str)
    except state.port("ValueError"):
        state.import_mode = state.port("ImportMode").AUTO
    state.strategy = state.port("get_strategy")(state.import_mode)


async def resolve_resume_watermarks(state: ResumeRunState) -> None:
    """Prefer frozen rules and preserve late live-rule imports."""
    state.watermark_patterns = []
    if state.snapshot:
        state.watermark_patterns = state.port("_deserialize_watermark_patterns")(
            state.snapshot
        )
        if not state.watermark_patterns:
            state.port("logger").warning(
                "resume: watermark_snapshot present but empty/unparsable for %s; falling back to live rules",
                state.values["pipeline_id"],
            )
    if not state.watermark_patterns:
        if not state.snapshot:
            state.port("logger").warning(
                "resume: legacy pipeline %s without watermark_snapshot, reloading from current rules",
                state.values["pipeline_id"],
            )
        try:
            from app.services.watermark_service import load_rules

            state.watermark_patterns = await load_rules(state.values["db"])
        except state.port("Exception") as exc:
            state.port("logger").warning(
                "resume: watermark load_rules failed (%s); using defaults", exc
            )
        if not state.watermark_patterns:
            from app.services.watermark_service import get_default_patterns

            state.watermark_patterns = get_default_patterns()
    state.shared = {
        "import_mode": state.import_mode,
        "strategy": state.strategy,
        "watermark_patterns": state.watermark_patterns,
    }


async def load_resume_hash_index(state: ResumeRunState) -> None:
    """Rebuild the shared index with completed batch IDs in one session."""
    state.hash_index = state.values["GlobalHashIndex"]()
    try:
        async with state.session_factory() as init_db:
            await state.hash_index.load(
                init_db, batch_ids=state.completed_batch_ids or None
            )
    except state.port("Exception"):
        state.port("logger").exception(
            "resume: GlobalHashIndex.load failed; similarity match will fallback"
        )
        state.hash_index = None
    if state.hash_index is not None:
        state.shared["hash_index"] = state.hash_index
