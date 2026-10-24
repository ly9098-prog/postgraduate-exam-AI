"""Visual-input and cache-freshness rules for AI error analysis."""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime
from typing import Protocol

from app.ai.prompts import AI_ANALYSIS_PROMPT_VERSION
from app.services.ai.analysis_content import (
    _normalize_ai_analysis,
    is_valid_ai_analysis,
)
from app.services.storage_backend import compress_image

MAX_VISUAL_IMAGES = 4


class VisualQuestion(Protocol):
    """Structural subset of Question needed by visual-source rules."""

    image_url: object
    content: dict
    options: dict | None


def detect_image_mime(data: bytes, fallback: str = "") -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if fallback.startswith("image/"):
        return fallback.split(";", 1)[0].strip().lower()
    return "image/jpeg"


def image_bytes_to_data_url(data: bytes, *, content_type: str = "") -> str:
    # Re-encode stored question images through PIL so malformed/non-image assets
    # are never forwarded to the analysis LLM.
    compressed = compress_image(data)
    mime = detect_image_mime(compressed, content_type)
    encoded = base64.b64encode(compressed).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def iter_url_values(value):
    if isinstance(value, str):
        text = value.strip()
        if text:
            yield text
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from iter_url_values(item)


def collect_question_visual_sources(question: VisualQuestion) -> list[str]:
    """Collect image/table-image URLs that are part of the question itself."""
    seen: set[str] = set()
    out: list[str] = []

    def add(value) -> None:
        for raw in iter_url_values(value):
            if raw not in seen:
                seen.add(raw)
                out.append(raw)

    add(question.image_url)
    content = question.content if isinstance(question.content, dict) else {}
    add(content.get("image_url"))
    segments = content.get("segments")
    if isinstance(segments, list):
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            seg_type = str(seg.get("type") or "").strip().lower()
            if seg_type in {"image", "math_image", "table_image", "code_image"}:
                add(seg.get("url"))
                add(seg.get("source_image_url"))
                add(seg.get("fallback_image_url"))
            elif seg_type == "table":
                add(seg.get("source_image_url"))
                add(seg.get("fallback_image_url"))
                add(seg.get("url"))

    # Some option schemas store an image next to text. Only inspect image-named
    # keys so arbitrary option strings can never be treated as remote URLs.
    options = question.options if isinstance(question.options, dict) else {}
    for value in options.values():
        if not isinstance(value, dict):
            continue
        add(value.get("image_url"))
        add(value.get("image"))

    return out[:MAX_VISUAL_IMAGES]


def question_has_unresolved_visual_slot(question: VisualQuestion) -> bool:
    """Return True when a declared raster visual has no loadable source URL.

    Text-only questions are valid inputs for wrong-detail analysis.  Native
    structured tables are serialized into text and can be handled without an
    image.
    """
    content = question.content if isinstance(question.content, dict) else {}
    segments = content.get("segments")
    if isinstance(segments, list):
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            seg_type = str(seg.get("type") or "").strip().lower()
            if seg_type not in {"image", "math_image", "table_image", "code_image"}:
                continue
            has_source = any(
                str(seg.get(key) or "").strip()
                for key in ("url", "source_image_url", "fallback_image_url")
            )
            if not has_source:
                return True

    # Empty ``image_url`` keys are common on text options; only an option that
    # explicitly declares itself image-bearing is visually incomplete.
    options = question.options if isinstance(question.options, dict) else {}
    for value in options.values():
        if not isinstance(value, dict):
            continue
        declares_image = (
            str(value.get("type") or "").strip().lower() in {"image", "math_image"}
            or value.get("has_image") is True
        )
        if declares_image:
            if not str(value.get("image_url") or value.get("image") or "").strip():
                return True

    return False


def extract_structured_visual(content: dict | None) -> str:
    """Serialize native table segments so a text model can still read them."""
    if not isinstance(content, dict):
        return ""
    segments = content.get("segments")
    if not isinstance(segments, list):
        return ""
    tables: list[dict] = []
    for seg in segments:
        if not isinstance(seg, dict) or str(seg.get("type") or "").lower() != "table":
            continue
        safe = {
            key: seg.get(key)
            for key in ("caption", "headers", "rows", "cells", "text", "markdown")
            if seg.get(key) not in (None, "", [], {})
        }
        if safe:
            tables.append(safe)
    if not tables:
        return ""
    try:
        return json.dumps(tables, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(tables)


def visual_evidence_is_valid(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"[\s_\-]+", "", text)
    return compact not in {
        "unreadable",
        "cannotread",
        "unabletoread",
        "novisualinput",
        "noimage",
        "无法读取",
        "无法识别",
        "图片无法读取",
        "图片无法识别",
        "未收到图片",
    }


def analysis_cache_age_ms(ai_analysis: dict | None) -> int | None:
    if not isinstance(ai_analysis, dict):
        return None
    meta = ai_analysis.get("_meta") or {}
    raw = str(meta.get("generated_at") or "").strip()
    if not raw:
        return None
    try:
        generated = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=UTC)
        return max(
            0,
            int((datetime.now(UTC) - generated.astimezone(UTC)).total_seconds() * 1000),
        )
    except (TypeError, ValueError):
        return None


def analysis_cache_stale_reason(
    ai_analysis: dict | None,
    *,
    requires_visual: bool = False,
    expected_input_signature: str | None = None,
    expected_model_signature: str | None = None,
) -> str | None:
    if not isinstance(ai_analysis, dict) or len(ai_analysis) == 0:
        return "empty"
    if not is_valid_ai_analysis(_normalize_ai_analysis(ai_analysis)):
        return "content_invalid"
    meta = ai_analysis.get("_meta") or {}
    if meta.get("version", "") != AI_ANALYSIS_PROMPT_VERSION:
        return "prompt_version"
    if meta.get("grounding_guard") not in {"passed", "repaired"}:
        return "grounding_guard"
    if requires_visual:
        if int(meta.get("visual_input_count") or 0) <= 0:
            return "visual_input"
        if not visual_evidence_is_valid(str(meta.get("visual_evidence") or "")):
            return "visual_evidence"
    if (
        expected_input_signature is not None
        and meta.get("input_signature") != expected_input_signature
    ):
        return "input_signature"
    if (
        expected_model_signature is not None
        and meta.get("model_signature") != expected_model_signature
    ):
        return "model_signature"
    return None


def is_ai_analysis_fresh(
    ai_analysis: dict | None,
    *,
    requires_visual: bool = False,
    expected_input_signature: str | None = None,
    expected_model_signature: str | None = None,
) -> bool:
    """Return whether a wrong-detail cache matches the current input/model.

    Visual evidence is mandatory only for questions that actually have a raster
    visual dependency.  Pure text questions intentionally cache with
    ``visual_input_count == 0``.
    """
    return (
        analysis_cache_stale_reason(
            ai_analysis,
            requires_visual=requires_visual,
            expected_input_signature=expected_input_signature,
            expected_model_signature=expected_model_signature,
        )
        is None
    )


def ai_analysis_generated_at(ai_analysis: dict | None) -> str | None:
    """Return the persisted generation marker used by timeout recovery."""
    if not isinstance(ai_analysis, dict):
        return None
    meta = ai_analysis.get("_meta")
    if not isinstance(meta, dict):
        return None
    value = str(meta.get("generated_at") or "").strip()
    return value or None


# Compatibility aliases preserve the historical service import surface used by
# callers and characterization tests.
_detect_image_mime = detect_image_mime
_image_bytes_to_data_url = image_bytes_to_data_url
_iter_url_values = iter_url_values
_collect_question_visual_sources = collect_question_visual_sources
_question_has_unresolved_visual_slot = question_has_unresolved_visual_slot
_extract_structured_visual = extract_structured_visual
_visual_evidence_is_valid = visual_evidence_is_valid
_analysis_cache_age_ms = analysis_cache_age_ms
_analysis_cache_stale_reason = analysis_cache_stale_reason
