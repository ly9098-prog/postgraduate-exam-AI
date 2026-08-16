import ast
import asyncio
import base64
import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import llm
from app.ai.gateway import chat_with_db_model, resolve_llm_runtime_config
from app.ai.context import build_error_context
from app.ai.fallback import get_fallback_advice, get_fallback_analysis
from app.ai.prompts import (
    AI_ANALYSIS_PROMPT_VERSION,
    build_error_analysis,
    build_study_advice,
)
from app.core.config import settings
from app.models.ai_chat import AiChat
from app.models.question import Question
from app.models.wrong_question import WrongQuestion
from app.services.knowledge_point_service import load_question_kps
from app.services.safe_remote_fetch import request_remote_bytes
from app.services.storage_backend import compress_image

logger = logging.getLogger(__name__)

# 微信小程序请求链路通常只有约 60 秒可用。模型调用必须在该预算内结束，
# 同时不能继续沿用原来的 25 秒硬截断，否则大量本可成功的请求会被误判超时。
_CONFIGURED_AI_TIMEOUT_SECONDS = max(10, int(settings.AI_TIMEOUT or 50))
ERROR_ANALYSIS_TIMEOUT_SECONDS = min(_CONFIGURED_AI_TIMEOUT_SECONDS, 48)
ERROR_ANALYSIS_FORCE_TIMEOUT_SECONDS = min(_CONFIGURED_AI_TIMEOUT_SECONDS, 50)
ERROR_ANALYSIS_TIMEOUT_GUARD_SECONDS = 2
ERROR_ANALYSIS_LOCK_GRACE_SECONDS = 15

# 同进程内生成中锁，防止并发重复调用大模型
_generating: set[int] = set()


def _pick_field(d: dict, candidates: list[str]) -> str:
    """Return the first non-empty normalized value from candidate keys."""
    for key in candidates:
        if key not in d:
            continue
        val = _coerce_analysis_text(d.get(key))
        if val:
            return val
    return ""


_ANALYSIS_WRAPPER_KEYS = ("content", "data", "result", "analysis", "ai_analysis", "payload")
_ANALYSIS_TEXT_KEYS = ("text", "content", "value", "description")
_DIAGNOSIS_KEYS = ("mistake_diagnosis", "error_analysis", "diagnosis", "mistakeDiagnosis", "mistakediagnosis", "错因诊断")
_KNOWLEDGE_KEYS = ("knowledge_patch", "knowledge_weakness", "knowledge", "knowledgePatch", "knowledgepatch", "补漏重点")
_TASK_KEYS = ("review_task", "suggestion", "task", "reviewTask", "reviewtask", "reviewask", "复练任务")
_EMPTY_ANALYSIS = {"mistake_diagnosis": "", "knowledge_patch": "", "review_task": ""}

# Vision context is deliberately bounded. A wrong-detail request should stay well
# below the mini-program's ~60s request budget and avoid sending full-resolution
# camera photos to a multimodal model.
_MAX_VISUAL_IMAGES = 4
_MAX_VISUAL_SOURCE_BYTES = 6 * 1024 * 1024
_VISUAL_FETCH_TIMEOUT_SECONDS = 6.0

# wrong-detail is a short, structured response task. Keep its output bounded and,
# for Qwen hybrid-thinking multimodal models, prefer direct answer mode. The
# persisted question images are already resized to <=1200px by compress_image;
# max_pixels further bounds the model-side visual token budget without adding an
# OCR/model hop.
_ERROR_ANALYSIS_MAX_TOKENS = 800
_ERROR_ANALYSIS_QWEN_MAX_PIXELS = 1024 * 1024


def _qwen_error_analysis_fast_path(provider: str | None, model: str | None) -> bool:
    """Whether the configured analysis model supports our Qwen fast path.

    Do not send provider-specific parameters to arbitrary OpenAI-compatible
    endpoints: the analysis model is DB-configurable and may be replaced later.
    """
    provider_key = str(provider or "").strip().lower()
    model_key = str(model or "").strip().lower()
    if not model_key:
        return False
    qwen_hybrid_prefixes = ("qwen3.7", "qwen3.6", "qwen3.5", "qwen3-vl")
    return model_key.startswith(qwen_hybrid_prefixes) and provider_key in {
        "qwen", "aliyun", "dashscope", "alibaba", "alibaba-cloud",
    }


def _detect_image_mime(data: bytes, fallback: str = "") -> str:
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


def _image_bytes_to_data_url(data: bytes, *, content_type: str = "") -> str:
    # Re-encode stored question images through PIL so malformed/non-image assets
    # are never forwarded to the analysis LLM.
    compressed = compress_image(data)
    mime = _detect_image_mime(compressed, content_type)
    encoded = base64.b64encode(compressed).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _iter_url_values(value):
    if isinstance(value, str):
        text = value.strip()
        if text:
            yield text
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_url_values(item)


def _collect_question_visual_sources(question: Question) -> list[str]:
    """Collect image/table-image URLs that are part of the question itself."""
    seen: set[str] = set()
    out: list[str] = []

    def add(value) -> None:
        for raw in _iter_url_values(value):
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

    return out[:_MAX_VISUAL_IMAGES]


def _question_has_unresolved_visual_slot(question: Question) -> bool:
    """Return True when the persisted question explicitly declares a raster visual
    but does not provide any loadable source URL.

    Text-only questions are valid inputs for wrong-detail analysis.  What should
    fail fast is the narrower case where the question schema itself says an
    image/math-image/table-image/code-image exists, yet the corresponding URL is
    missing.  Native structured tables are *not* treated as missing images: they
    are serialized into text by ``_extract_structured_visual`` and can be handled
    by the normal analysis LLM without a raster image.
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

    # Option-image schemas may include an empty ``image_url`` key even for a
    # normal text option, so only treat the option as visually incomplete when
    # it explicitly declares itself as an image-bearing option.
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


def _extract_structured_visual(content: dict | None) -> str:
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


def _read_local_public_asset(url: str) -> tuple[bytes, str] | None:
    """Read our own /static asset without doing an SSRF-prone HTTP round trip."""
    raw = str(url or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    path = unquote(parsed.path if parsed.scheme else raw.split("?", 1)[0])
    public_base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    if parsed.scheme and public_base and not raw.startswith(public_base + "/"):
        return None
    if not path.startswith("/static/"):
        return None

    # services/ai_service.py lives under <repo>/app/services in production.
    repo_root = Path(__file__).resolve().parents[2]
    static_root = (repo_root / "static").resolve()
    candidate = (repo_root / path.lstrip("/")).resolve()
    try:
        candidate.relative_to(static_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    size = candidate.stat().st_size
    if size < 1 or size > _MAX_VISUAL_SOURCE_BYTES:
        return None
    data = candidate.read_bytes()
    return data, _detect_image_mime(data)


async def _visual_source_to_data_url(url: str) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    if raw.startswith("data:image/"):
        # Existing data URLs are accepted only when bounded and syntactically
        # simple. They will still be decoded/re-encoded by the caller when they
        # originate from uploads; this branch is for stored question content.
        if len(raw) <= (_MAX_VISUAL_SOURCE_BYTES * 2):
            return raw
        return None

    local = await asyncio.to_thread(_read_local_public_asset, raw)
    if local is not None:
        data, content_type = local
        try:
            return _image_bytes_to_data_url(data, content_type=content_type)
        except Exception:
            return None

    if not raw.startswith(("https://", "http://")):
        return None
    try:
        remote = await asyncio.to_thread(
            request_remote_bytes,
            raw,
            max_bytes=_MAX_VISUAL_SOURCE_BYTES,
            timeout=_VISUAL_FETCH_TIMEOUT_SECONDS,
            allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
            follow_redirects=True,
            max_redirects=2,
            require_2xx=True,
            headers={"Accept": "image/*"},
        )
        return _image_bytes_to_data_url(remote.data, content_type=remote.content_type)
    except Exception:
        logger.warning("ai.error_analysis.visual_fetch_failed url=%s", raw[:180])
        return None


async def _prepare_visual_inputs(question: Question) -> tuple[list[str], dict]:
    """Load visual inputs only from the persisted question record.

    wrong-detail does not accept user-supplied screenshots. The question image
    stored in the database/object storage is the single source of truth for
    questions that actually contain raster visuals.  Text-only questions
    legitimately return an empty image list and continue through the text path;
    callers only fail when a declared visual asset cannot be resolved.
    """
    sources = _collect_question_visual_sources(question)
    data_urls: list[str] = []

    if sources:
        resolved = await asyncio.gather(
            *(_visual_source_to_data_url(source) for source in sources[:_MAX_VISUAL_IMAGES]),
            return_exceptions=False,
        )
        for data_url in resolved:
            if len(data_urls) >= _MAX_VISUAL_IMAGES:
                break
            if data_url and data_url not in data_urls:
                data_urls.append(data_url)

    return data_urls, {
        "declared_source_count": len(sources),
        "loaded_count": len(data_urls),
        "structured_visual": _extract_structured_visual(question.content),
    }

def _extract_visual_evidence(raw: str) -> str:
    decoded = _decode_structured_content(raw or "")

    def find(value, depth: int = 0) -> str:
        if depth > 5:
            return ""
        if isinstance(value, dict):
            for key in ("visual_evidence", "visualEvidence", "image_evidence"):
                if key in value:
                    return _coerce_analysis_text(value.get(key), depth + 1)
            for key in _ANALYSIS_WRAPPER_KEYS:
                if key in value:
                    found = find(value.get(key), depth + 1)
                    if found:
                        return found
        elif isinstance(value, list):
            for item in value:
                found = find(item, depth + 1)
                if found:
                    return found
        return ""

    return find(decoded)


def _visual_evidence_is_valid(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"[\s_\-]+", "", text)
    return compact not in {
        "unreadable", "cannotread", "unabletoread", "novisualinput", "noimage",
        "无法读取", "无法识别", "图片无法读取", "图片无法识别", "未收到图片",
    }


def _coerce_analysis_text(value, depth: int = 0) -> str:
    """Normalize common model field shapes (string/list/nested object) to text."""
    if value is None or depth > 6:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _coerce_analysis_text(item, depth + 1)
            if text and text not in parts:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(value, dict):
        for key in _ANALYSIS_TEXT_KEYS:
            if key in value:
                text = _coerce_analysis_text(value.get(key), depth + 1)
                if text:
                    return text
        # 某些模型会把正文放进只有一个字段的对象中。
        if len(value) == 1:
            return _coerce_analysis_text(next(iter(value.values())), depth + 1)
    return ""


def _extract_analysis_fields(value, depth: int = 0) -> dict:
    if depth > 6 or value is None:
        return dict(_EMPTY_ANALYSIS)

    if isinstance(value, str):
        decoded = _decode_structured_content(value)
        if decoded is not None and not (
            isinstance(decoded, str) and decoded.strip() == value.strip()
        ):
            return _extract_analysis_fields(decoded, depth + 1)
        return _parse_titled_analysis_text(value)

    if isinstance(value, list):
        best = dict(_EMPTY_ANALYSIS)
        best_score = -1
        for item in value:
            candidate = _extract_analysis_fields(item, depth + 1)
            score = sum(bool(candidate.get(k)) for k in _EMPTY_ANALYSIS)
            if score > best_score:
                best = candidate
                best_score = score
        if best_score > 0:
            return best
        text = _coerce_analysis_text(value, depth + 1)
        return {"mistake_diagnosis": text, "knowledge_patch": "", "review_task": ""}

    if not isinstance(value, dict):
        text = _coerce_analysis_text(value, depth + 1)
        return {"mistake_diagnosis": text, "knowledge_patch": "", "review_task": ""}

    direct = {
        "mistake_diagnosis": _pick_field(value, list(_DIAGNOSIS_KEYS)),
        "knowledge_patch": _pick_field(value, list(_KNOWLEDGE_KEYS)),
        "review_task": _pick_field(value, list(_TASK_KEYS)),
    }
    if is_valid_ai_analysis(direct):
        return direct

    # 优先解包常见响应包装层，再兜底搜索其余嵌套对象。
    nested_values = [value[key] for key in _ANALYSIS_WRAPPER_KEYS if key in value]
    nested_values.extend(v for k, v in value.items() if k not in _ANALYSIS_WRAPPER_KEYS and isinstance(v, (dict, list, str)))
    best = direct
    best_score = 0
    for nested in nested_values:
        candidate = _extract_analysis_fields(nested, depth + 1)
        score = sum(bool(candidate.get(k)) for k in _EMPTY_ANALYSIS)
        if score > best_score:
            best = candidate
            best_score = score
            if score == 3:
                break
    return best


def _strip_code_fence(text: str) -> str:
    match = re.search(r"```(?:json|javascript|js)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    return match.group(1).strip() if match else text.strip()


def _decode_structured_content(raw: str):
    """Decode JSON/Python-literal model output, including text around the object."""
    text = _strip_code_fence((raw or "").strip())
    if not text:
        return None

    starts = [0]
    starts.extend(i for i, ch in enumerate(text) if i > 0 and ch in "{[")
    decoder = json.JSONDecoder()
    for start in starts:
        candidate = text[start:].lstrip()
        if not candidate:
            continue
        try:
            value, _ = decoder.raw_decode(candidate)
            return value
        except (json.JSONDecodeError, ValueError):
            pass
        try:
            value = ast.literal_eval(candidate)
            if isinstance(value, (dict, list, str)):
                return value
        except (SyntaxError, ValueError):
            pass
    return None


def _parse_titled_analysis_text(text: str) -> dict:
    stripped = _strip_code_fence(text)
    heading_re = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:\d+[.、)]\s*)?(?:[-*]\s*)?"
        r"(?:\*\*)?\s*(错因诊断|补漏重点|复练任务)\s*(?:\*\*)?\s*[：:]\s*(?:\*\*)?\s*"
    )
    matches = list(heading_re.finditer(stripped))
    if not matches:
        return {"mistake_diagnosis": stripped, "knowledge_patch": "", "review_task": ""}

    result = dict(_EMPTY_ANALYSIS)
    key_map = {"错因诊断": "mistake_diagnosis", "补漏重点": "knowledge_patch", "复练任务": "review_task"}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(stripped)
        result[key_map[match.group(1)]] = stripped[match.end():end].strip()
    return result


def parse_error_analysis_content(raw: str) -> dict:
    """
    鲁棒解析 AI 返回内容，兼容：
    1. 标准 JSON
    2. ```json ... ``` 代码块
    3. JSON 前后有解释文字
    4. 字段名不完全一致（snake_case / camelCase / 全小写 / 中文）
    5. 字段值为 JSON 字符串（自动解包）
    6. 非 JSON 但包含三段式中文文本
    返回结构：{mistake_diagnosis, knowledge_patch, review_task}
    """
    text = (raw or '').strip()
    if not text:
        return dict(_EMPTY_ANALYSIS)
    decoded = _decode_structured_content(text)
    return _extract_analysis_fields(decoded if decoded is not None else text)


def is_valid_ai_analysis(content: dict) -> bool:
    return any(str(content.get(k, "")).strip() for k in ["mistake_diagnosis", "knowledge_patch", "review_task"])


def _normalize_ai_analysis(cached: dict) -> dict:
    """Convert any field-name format to canonical snake_case."""
    return _extract_analysis_fields(cached) if cached else dict(_EMPTY_ANALYSIS)


def _analysis_input_signature(
    wq: WrongQuestion,
    q: Question,
    knowledge_points: list[str] | None,
    *,
    visual_sources: list[str] | None = None,
) -> str:
    """Hash every persisted input that can materially change wrong-detail advice.

    The digest lets us invalidate a cache when the question, answer, visual
    source, user's latest wrong answer, error classification, review count, or
    knowledge-point mapping changes without storing duplicate source content in
    ``_meta``.  ``default=str`` keeps the signature deterministic for datetime
    or enum-like values that may appear in JSON payloads.
    """
    payload = {
        "prompt_version": AI_ANALYSIS_PROMPT_VERSION,
        "question_id": q.id,
        "question_sync_version": getattr(q, "sync_version", None),
        "question_updated_at": getattr(q, "updated_at", None),
        "content": q.content,
        "options": q.options,
        "answer": q.answer,
        "image_sources": visual_sources if visual_sources is not None else _collect_question_visual_sources(q),
        "knowledge_points": list(knowledge_points or []),
        "wrong_answer": wq.wrong_answer,
        "error_type": wq.error_type,
        "review_count": int(wq.review_count or 0),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _analysis_model_signature(runtime) -> str | None:
    """Return a stable digest for the currently selected analysis model."""
    if runtime is None:
        return None
    payload = {
        "model_config_id": runtime.model_config_id,
        "provider": runtime.provider,
        "model_name": runtime.model_name,
        "base_url": runtime.base_url,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _analysis_cache_age_ms(ai_analysis: dict | None) -> int | None:
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
        return max(0, int((datetime.now(UTC) - generated.astimezone(UTC)).total_seconds() * 1000))
    except (TypeError, ValueError):
        return None


def _analysis_cache_stale_reason(
    ai_analysis: dict | None,
    *,
    requires_visual: bool = False,
    expected_input_signature: str | None = None,
    expected_model_signature: str | None = None,
) -> str | None:
    if not isinstance(ai_analysis, dict) or len(ai_analysis) == 0:
        return "empty"
    meta = ai_analysis.get("_meta") or {}
    if meta.get("version", "") != AI_ANALYSIS_PROMPT_VERSION:
        return "prompt_version"
    if requires_visual:
        if int(meta.get("visual_input_count") or 0) <= 0:
            return "visual_input"
        if not _visual_evidence_is_valid(str(meta.get("visual_evidence") or "")):
            return "visual_evidence"
    if expected_input_signature is not None and meta.get("input_signature") != expected_input_signature:
        return "input_signature"
    if expected_model_signature is not None and meta.get("model_signature") != expected_model_signature:
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
    return _analysis_cache_stale_reason(
        ai_analysis,
        requires_visual=requires_visual,
        expected_input_signature=expected_input_signature,
        expected_model_signature=expected_model_signature,
    ) is None


def build_cached_error_analysis_response(
    wq,
    *,
    requires_visual: bool = False,
    expected_input_signature: str | None = None,
    expected_model_signature: str | None = None,
) -> dict | None:
    """If the wrong question has a fresh cached AI analysis, return it; otherwise None."""
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
    }


def build_any_cached_error_analysis_response(wq) -> dict | None:
    """
    Return any cached AI analysis regardless of prompt version freshness.
    Used as fallback when force_regenerate fails — preserves old content
    even if the cache was generated with an older prompt version.
    """
    if not isinstance(wq.ai_analysis, dict) or not wq.ai_analysis:
        return None
    content = _normalize_ai_analysis(wq.ai_analysis)
    if not is_valid_ai_analysis(content):
        return None
    meta = (wq.ai_analysis or {}).get("_meta") or {}
    return {
        "content": content,
        "from_cache": True,
        "from_fallback": False,
        "tokens_used": 0,
        "model": "cache_preserved",
        "duration_ms": 0,
        "force_regenerated": False,
        "cache_preserved": True,
        "visual_input_count": int(meta.get("visual_input_count") or 0),
        "visual_evidence": meta.get("visual_evidence") or None,
    }


async def evaluate_cached_error_analysis(
    db: AsyncSession,
    wq: WrongQuestion,
    q: Question,
    *,
    knowledge_points: list[str] | None = None,
) -> dict:
    """Evaluate whether ``wrong_questions.ai_analysis`` is safe to show directly.

    The wrong-detail endpoint embeds cached AI content in its initial payload,
    so it must use the same freshness rules as ``analyze_error``. Returning a
    stale cache here would make prewarm/version invalidation ineffective because
    the mini-program could render the old content before calling the AI endpoint.
    """
    if not isinstance(wq.ai_analysis, dict) or not wq.ai_analysis:
        return {"status": "empty", "analysis": None, "reason": "empty"}

    visual_sources = _collect_question_visual_sources(q)
    requires_visual = bool(visual_sources) or _question_has_unresolved_visual_slot(q)
    if requires_visual and not visual_sources:
        return {"status": "stale", "analysis": None, "reason": "visual_input_missing"}

    if knowledge_points is None:
        kp_map = await load_question_kps(db, [q.id])
        knowledge_points = kp_map.get(q.id, [])
    runtime = await resolve_llm_runtime_config(db, feature="analysis")
    input_signature = _analysis_input_signature(
        wq, q, knowledge_points, visual_sources=visual_sources
    )
    model_signature = _analysis_model_signature(runtime)
    reason = _analysis_cache_stale_reason(
        wq.ai_analysis,
        requires_visual=requires_visual,
        expected_input_signature=input_signature,
        expected_model_signature=model_signature,
    )
    if reason is not None:
        logger.info(
            "ai.error_analysis.detail_cache_stale wq_id=%d user_id=%d reason=%s",
            wq.id, wq.user_id, reason,
        )
        return {"status": "stale", "analysis": None, "reason": reason}
    age_ms = _analysis_cache_age_ms(wq.ai_analysis)
    logger.info(
        "ai.error_analysis.detail_cache_hit wq_id=%d user_id=%d age_ms=%s model=%s",
        wq.id, wq.user_id, age_ms,
        ((wq.ai_analysis or {}).get("_meta") or {}).get("model") or "unknown",
    )
    return {
        "status": "ready",
        "analysis": wq.ai_analysis,
        "reason": None,
        "age_ms": age_ms,
    }


async def analyze_error(
    db: AsyncSession,
    user_id: int,
    wrong_question_id: int,
    force_regenerate: bool = False,
) -> dict:
    wq_result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id == wrong_question_id,
            WrongQuestion.user_id == user_id,
        )
    )
    wq = wq_result.scalar_one_or_none()
    if not wq:
        raise ValueError("错题记录不存在")

    q_result = await db.execute(select(Question).where(Question.id == wq.question_id))
    q = q_result.scalar_one_or_none()
    if not q:
        raise ValueError("题目不存在")

    stored_visual_sources = _collect_question_visual_sources(q)
    requires_visual = bool(stored_visual_sources) or _question_has_unresolved_visual_slot(q)
    # Pure text questions are valid and continue through the normal analysis
    # path.  Fail fast only when the question schema explicitly declares a
    # visual element but the persisted asset URL is missing.
    if requires_visual and not stored_visual_sources:
        logger.info(
            "ai.error_analysis.image_missing wq_id=%d question_id=%d reason=declared_visual_without_source",
            wq.id, q.id,
        )
        return {
            "content": get_fallback_analysis(),
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "vision_input_missing",
            "duration_ms": 0,
            "force_regenerated": False,
            "cache_preserved": False,
            "visual_input_count": 0,
        }

    kp_map = await load_question_kps(db, [q.id])
    knowledge_points = kp_map.get(q.id, [])
    # Resolve the currently selected analysis model before the cache decision.
    # This is a cheap DB lookup compared with an LLM call and lets a model
    # configuration change invalidate old advice deterministically.
    runtime = await resolve_llm_runtime_config(db, feature="analysis")
    input_signature = _analysis_input_signature(
        wq, q, knowledge_points, visual_sources=stored_visual_sources
    )
    model_signature = _analysis_model_signature(runtime)

    effective_force = bool(force_regenerate)

    if not effective_force:
        cached = build_cached_error_analysis_response(
            wq,
            requires_visual=requires_visual,
            expected_input_signature=input_signature,
            expected_model_signature=model_signature,
        )
        if cached is not None:
            logger.info(
                "ai.error_analysis.cache_hit wq_id=%d user_id=%d age_ms=%s model=%s",
                wq.id, user_id, _analysis_cache_age_ms(wq.ai_analysis),
                ((wq.ai_analysis or {}).get("_meta") or {}).get("model") or "unknown",
            )
            return cached
        stale_reason = _analysis_cache_stale_reason(
            wq.ai_analysis,
            requires_visual=requires_visual,
            expected_input_signature=input_signature,
            expected_model_signature=model_signature,
        )
        logger.info(
            "ai.error_analysis.cache_miss wq_id=%d user_id=%d reason=%s",
            wq.id, user_id, stale_reason or "unknown",
        )
    else:
        logger.info(
            "force regenerate error analysis wq_id=%d user_id=%d",
            wq.id, user_id,
        )

    timeout_sec = (
        ERROR_ANALYSIS_FORCE_TIMEOUT_SECONDS
        if effective_force else ERROR_ANALYSIS_TIMEOUT_SECONDS
    )

    wq_pk = wq.id
    if wq_pk in _generating:
        return {
            "content": {"mistake_diagnosis": "AI 分析正在生成中，请稍后刷新查看", "knowledge_patch": "", "review_task": ""},
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "generating",
            "duration_ms": 0,
        }
    _generating.add(wq_pk)

    from app.core.cache import cache
    lock_key = f"ai:error_analysis:{wq_pk}"
    lock_value = f"{user_id}:{uuid.uuid4().hex}"
    lock_ttl = timeout_sec + ERROR_ANALYSIS_LOCK_GRACE_SECONDS
    try:
        have_lock = await cache.acquire_lock(lock_key, lock_value, ttl=lock_ttl)
    except Exception:
        _generating.discard(wq_pk)
        raise
    if not have_lock and cache.is_enabled:
        _generating.discard(wq_pk)
        return {
            "content": {"mistake_diagnosis": "AI 分析正在生成中，请稍后刷新查看", "knowledge_patch": "", "review_task": ""},
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "generating",
            "duration_ms": 0,
        }

    try:
        await db.refresh(wq)
        # The same wrong-question row can be updated while this request waits
        # for the cross-process generation lock. Recompute the digest so a
        # just-written cache is only reused if it matches the latest answer.
        input_signature = _analysis_input_signature(
            wq, q, knowledge_points, visual_sources=stored_visual_sources
        )
        if not effective_force:
            cached = build_cached_error_analysis_response(
                wq,
                requires_visual=requires_visual,
                expected_input_signature=input_signature,
                expected_model_signature=model_signature,
            )
            if cached is not None:
                logger.info(
                    "ai.error_analysis.cache_hit_after_lock wq_id=%d user_id=%d age_ms=%s",
                    wq.id, user_id, _analysis_cache_age_ms(wq.ai_analysis),
                )
                return cached

        image_data_urls, visual_meta = await _prepare_visual_inputs(q)
        structured_visual = str(visual_meta.get("structured_visual") or "")

        # If the question really contains a raster visual, every declared asset
        # failing to load is a hard failure.  A genuine text-only question has
        # zero images by design and should continue with a text LLM request.
        if requires_visual and not image_data_urls:
            logger.info(
                "ai.error_analysis.image_load_failed wq_id=%d question_id=%d declared_sources=%d",
                wq.id, q.id, int(visual_meta.get("declared_source_count") or 0),
            )
            return {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": "vision_input_missing",
                "duration_ms": 0,
                "force_regenerated": False,
                "cache_preserved": False,
                "visual_input_count": 0,
            }

        # Wrong-detail AI analysis must always use the same DB-configured
        # analysis LLM as the original text-only flow. Images are passed
        # directly to that model as multimodal message content; OCR/VL model
        # routing is intentionally not used here.
        if runtime is None:
            return {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": "vision_unavailable" if image_data_urls else "fallback",
                "duration_ms": 0,
                "force_regenerated": False,
                "cache_preserved": False,
                "visual_input_count": len(image_data_urls),
            }

        context = build_error_context(wq, q, knowledge_points)
        context["question"]["structured_visual"] = structured_visual
        qwen_fast_path = _qwen_error_analysis_fast_path(runtime.provider, runtime.model_name)
        image_max_pixels = _ERROR_ANALYSIS_QWEN_MAX_PIXELS if qwen_fast_path else None
        llm_extra_body = {"enable_thinking": False} if qwen_fast_path else None
        messages = build_error_analysis(
            context["question"],
            wq.wrong_answer,
            q.answer,
            image_data_urls=image_data_urls,
            image_max_pixels=image_max_pixels,
        )

        # The mini-program request has a ~58s client budget. Resolving the
        # persisted question image may consume a few seconds, so keep response
        # headroom instead of spending the full timeout in the LLM call.
        model_timeout_sec = min(timeout_sec, 46) if image_data_urls else timeout_sec
        try:
            async with asyncio.timeout(model_timeout_sec + ERROR_ANALYSIS_TIMEOUT_GUARD_SECONDS):
                result = await llm.chat(
                    messages,
                    temperature=0.2,
                    model=runtime.model_name,
                    api_key=runtime.api_key,
                    base_url=runtime.base_url,
                    provider=runtime.provider,
                    timeout=model_timeout_sec,
                    max_tokens=_ERROR_ANALYSIS_MAX_TOKENS,
                    extra_body=llm_extra_body,
                )
        except TimeoutError:
            old_cache = build_any_cached_error_analysis_response(wq)
            logger.warning(
                "ai.error_analysis.timeout wq_id=%s force=%s visual=%s timeout_sec=%s has_old_cache=%s",
                wq.id, effective_force, bool(image_data_urls), model_timeout_sec, bool(old_cache),
            )
            return {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": "timeout",
                "duration_ms": model_timeout_sec * 1000,
                "force_regenerated": False,
                "cache_preserved": False,
                "visual_input_count": len(image_data_urls),
            }
        except Exception as exc:
            old_cache = build_any_cached_error_analysis_response(wq)
            logger.exception(
                "ai.error_analysis.exception wq_id=%s force=%s visual=%s err=%s has_old_cache=%s",
                wq.id, effective_force, bool(image_data_urls), repr(exc), bool(old_cache),
            )
            error_text = str(exc).lower()
            looks_like_vision_rejection = bool(image_data_urls) and any(
                token in error_text
                for token in ("image", "vision", "multimodal", "image_url", "content type")
            )
            return {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "tokens_used": 0,
                "model": "vision_unavailable" if looks_like_vision_rejection else "fallback",
                "duration_ms": 0,
                "force_regenerated": False,
                "cache_preserved": False,
                "visual_input_count": len(image_data_urls),
            }

        raw_content = result.get("content", "")
        parsed = parse_error_analysis_content(raw_content)
        parsed_valid = is_valid_ai_analysis(parsed)
        visual_evidence = _extract_visual_evidence(raw_content) if image_data_urls else ""

        if image_data_urls and not _visual_evidence_is_valid(visual_evidence):
            logger.info(
                "ai.error_analysis.visual_ack_failed wq_id=%s model=%s evidence=%r",
                wq.id, result.get("model"), visual_evidence[:120],
            )
            return {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "model": "vision_parse_failed",
                "tokens_used": result.get("tokens_used", 0),
                "duration_ms": result.get("duration_ms", 0),
                "force_regenerated": False,
                "cache_preserved": False,
                "visual_input_count": len(image_data_urls),
            }

        if not parsed_valid:
            resp = {
                "content": get_fallback_analysis(),
                "from_cache": False,
                "from_fallback": True,
                "model": "parse_failed",
                "tokens_used": 0,
                "duration_ms": 0,
                "visual_input_count": len(image_data_urls),
            }
            if effective_force:
                resp["force_regenerated"] = False
                resp["cache_preserved"] = False
            logger.info(
                "ai.error_analysis.empty wq_id=%s force=%s model=parse_failed",
                wq.id, effective_force,
            )
            return resp

        parsed["_meta"] = {
            "model": result.get("model", ""),
            "provider": runtime.provider,
            "model_config_id": runtime.model_config_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "version": AI_ANALYSIS_PROMPT_VERSION,
            "from_fallback": False,
            "force_regenerated": effective_force,
            "visual_input_count": len(image_data_urls),
            "visual_evidence": visual_evidence or None,
            "input_mode": "vision" if image_data_urls else "text",
            "input_signature": input_signature,
            "model_signature": model_signature,
        }

        wq.ai_analysis = parsed
        await db.commit()

        context_snapshot = dict(context)
        context_snapshot["visual_input_count"] = len(image_data_urls)
        context_snapshot["visual_evidence"] = visual_evidence or None
        # Never persist base64 image payloads in chat logs/context snapshots.
        db.add(AiChat(
            user_id=user_id,
            session_type="error_analysis",
            user_message=str(context["question"]),
            ai_response=result["content"],
            context_snapshot=context_snapshot,
            tokens_used=result["tokens_used"],
            model=result["model"],
            duration_ms=result["duration_ms"],
        ))
        await db.commit()

        logger.info(
            "ai.error_analysis.result wq_id=%s force=%s model=%s input_mode=%s visual_count=%s "
            "visual_evidence_valid=%s parsed_valid=%s thinking=%s max_tokens=%s "
            "image_max_pixels=%s fields=%s duration_ms=%s",
            wq.id, effective_force, result.get("model"),
            "vision" if image_data_urls else "text", len(image_data_urls),
            _visual_evidence_is_valid(visual_evidence) if image_data_urls else None,
            parsed_valid, False if qwen_fast_path else "default",
            _ERROR_ANALYSIS_MAX_TOKENS, image_max_pixels,
            {k: bool(parsed.get(k)) for k in ["mistake_diagnosis", "knowledge_patch", "review_task"]},
            result.get("duration_ms"),
        )

        return {
            "content": parsed,
            "from_cache": False,
            "from_fallback": False,
            "tokens_used": result.get("tokens_used", 0),
            "model": result.get("model", ""),
            "duration_ms": result.get("duration_ms", 0),
            "force_regenerated": effective_force,
            "visual_input_count": len(image_data_urls),
            "visual_evidence": visual_evidence or None,
            "input_mode": "vision" if image_data_urls else "text",
        }
    finally:
        _generating.discard(wq_pk)
        if have_lock:
            try:
                await cache.release_lock(lock_key, lock_value)
            except Exception:
                pass


async def prewarm_wrong_question_analysis(
    wrong_question_id: int,
    user_id: int,
    *,
    expected_revision: str | None = None,
) -> None:
    """后台预生成错题 AI 分析。独立 session。

    Exceptions propagate to the durable worker, which handles retry/dead-letter
    via the failing task's fail_v2 path. The function itself does NOT catch
    exceptions to allow proper retry semantics.
    """
    import logging
    logger = logging.getLogger(__name__)
    from app.core.database import async_session
    async with async_session() as bg_db:
        wq = await bg_db.execute(
            select(WrongQuestion).where(
                WrongQuestion.id == wrong_question_id,
                WrongQuestion.user_id == user_id,
            )
        )
        wq = wq.scalar_one_or_none()
        if not wq:
            logger.info("[prewarm] wrong_question not found id=%d uid=%d", wrong_question_id, user_id)
            return
        if expected_revision:
            from app.services.ai_prewarm_worker import build_prewarm_revision

            current_revision = build_prewarm_revision(
                review_count=wq.review_count,
                wrong_answer=wq.wrong_answer,
            )
            if current_revision != expected_revision:
                logger.info(
                    "[prewarm] superseded id=%d uid=%d expected_revision=%s current_revision=%s",
                    wrong_question_id, user_id, expected_revision, current_revision,
                )
                return

        # Reuse the canonical analysis path. It performs full input/model cache
        # validation, cross-process locking, and returns immediately on a hit.
        result = await analyze_error(bg_db, user_id, wrong_question_id)
        logger.info(
            "[prewarm] done id=%d uid=%d revision=%s from_cache=%s from_fallback=%s model=%s duration_ms=%s",
            wrong_question_id, user_id,
            expected_revision or "legacy",
            result.get("from_cache"), result.get("from_fallback"),
            result.get("model"), result.get("duration_ms"),
        )


async def generate_advice(db: AsyncSession, user_id: int, subject_id: int | None = None) -> dict:
    runtime = await resolve_llm_runtime_config(db, feature="analysis")

    if runtime is None:
        return {
            "content": get_fallback_advice(),
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "fallback",
            "duration_ms": 0,
        }

    # Collect user's wrong question stats
    conditions = [WrongQuestion.user_id == user_id]
    result = await db.execute(
        select(WrongQuestion).where(*conditions).limit(10)
    )
    wrong_list = result.scalars().all()

    qids = [w.question_id for w in wrong_list]
    questions = {}
    if qids:
        qr = await db.execute(
            select(Question).where(Question.id.in_(qids))
        )
        questions = {q.id: q for q in qr.scalars().all()}
    kp_map = await load_question_kps(db, qids)

    weak_points = set()
    subject_stats = {}
    recent_wrong = []
    for w in wrong_list:
        q = questions.get(w.question_id)
        if q:
            weak_points.update(kp_map.get(q.id, []))
            # Use subject_id as label (subject_ref is noload, always None without selectinload)
            subj_label = str(q.subject_id)
            subject_stats[subj_label] = subject_stats.get(subj_label, 0) + 1
            recent_wrong.append({
                "subject_id": q.subject_id,
                "error_type": w.error_type,
                "wrong_answer": w.wrong_answer,
                "correct_answer": q.answer,
            })

    messages = build_study_advice(
        [{"subject": k, "count": v} for k, v in subject_stats.items()],
        list(weak_points),
        recent_wrong,
    )

    try:
        result = await chat_with_db_model(db, messages, feature="analysis")
        if result is None:
            raise RuntimeError("AI分析模型未配置")
    except Exception:
        fallback = get_fallback_advice()
        return {
            "content": fallback,
            "from_cache": False,
            "from_fallback": True,
            "tokens_used": 0,
            "model": "fallback",
            "duration_ms": 0,
        }

    try:
        parsed = json.loads(result["content"])
    except (json.JSONDecodeError, KeyError):
        parsed = {"overall_assessment": result["content"]}

    db.add(AiChat(
        user_id=user_id,
        session_type="study_advice",
        user_message=str(subject_stats),
        ai_response=result["content"],
        tokens_used=result["tokens_used"],
        model=result["model"],
        duration_ms=result["duration_ms"],
    ))
    await db.commit()

    return {
        "content": parsed,
        "from_cache": False,
        "from_fallback": False,
        "tokens_used": result["tokens_used"],
        "model": result["model"],
        "duration_ms": result["duration_ms"],
    }
