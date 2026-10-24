"""Input/model signatures and response projection for analysis caches."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.ai.prompts import AI_ANALYSIS_PROMPT_VERSION
from app.services.ai.analysis_content import _normalize_ai_analysis
from app.services.ai.visual_cache import (
    ai_analysis_generated_at,
    collect_question_visual_sources,
    is_ai_analysis_fresh,
)


def analysis_input_signature(
    wq: Any,
    q: Any,
    knowledge_points: list[str] | None,
    *,
    visual_sources: list[str] | None = None,
) -> str:
    """Hash persisted inputs that can materially change wrong-detail advice."""
    payload = {
        "prompt_version": AI_ANALYSIS_PROMPT_VERSION,
        "question_id": q.id,
        "wrong_question_version_id": getattr(wq, "question_version_id", None),
        "question_version_id": (
            getattr(q, "question_version_id", None)
            or getattr(q, "current_version_id", None)
        ),
        "question_sync_version": getattr(q, "sync_version", None),
        "question_updated_at": getattr(q, "updated_at", None),
        "question_type": getattr(q, "question_type", None),
        "content": q.content,
        "options": q.options,
        "answer": q.answer,
        "image_sources": visual_sources
        if visual_sources is not None
        else collect_question_visual_sources(q),
        "knowledge_points": list(knowledge_points or []),
        "wrong_answer": wq.wrong_answer,
        "error_type": wq.error_type,
        "review_count": int(wq.review_count or 0),
    }
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def analysis_model_signature(runtime: Any) -> str | None:
    """Return a stable digest for the currently selected analysis model."""
    if runtime is None:
        return None
    payload = {
        "model_config_id": runtime.model_config_id,
        "provider": runtime.provider,
        "model_name": runtime.model_name,
        "base_url": runtime.base_url,
    }
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_cached_error_analysis_response(
    wq,
    *,
    requires_visual: bool = False,
    expected_input_signature: str | None = None,
    expected_model_signature: str | None = None,
) -> dict | None:
    """Return a fresh cached response projection, or None for a cache miss."""
    if not is_ai_analysis_fresh(
        wq.ai_analysis,
        requires_visual=requires_visual,
        expected_input_signature=expected_input_signature,
        expected_model_signature=expected_model_signature,
    ):
        return None
    meta = (wq.ai_analysis or {}).get("_meta") or {}
    return {
        "content": _normalize_ai_analysis(wq.ai_analysis),
        "from_cache": True,
        "from_fallback": False,
        "tokens_used": 0,
        "model": "cache",
        "duration_ms": 0,
        "visual_input_count": int(meta.get("visual_input_count") or 0),
        "visual_evidence": meta.get("visual_evidence") or None,
        "generated_at": ai_analysis_generated_at(wq.ai_analysis),
    }


# Compatibility aliases preserve the historical ai_service import surface.
_analysis_input_signature = analysis_input_signature
_analysis_model_signature = analysis_model_signature
