"""Stage 8 导入流水线编排 — 串联 Stage 1-7 模块。

Pipeline stages:
    extract → normalize_text → split → match → normalize_schema → [repair] → review

Features:
- Task state tracking per stage
- Error isolation (single question failure doesn't block others)
- AI repair toggle via config
- Background execution with in-memory state store
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any

from app.features.import_mode import ImportMode, detect_import_mode, get_strategy
from app.features.ocr_correction_common import (
    TIER_HIGH_THRESHOLD,
    _detect_noise, _detect_structure_abnormal, _filter_sensitive, _should_correct,
)
from app.features.page_classifier import classify_pages, filter_blocks_by_classification
from app.features.pipeline_artifacts import (
    cleanup_artifacts as _pipeline_cleanup_artifacts,
    find_resumable_stage as _find_resumable_stage,
    list_artifacts as _list_artifacts,
    load_artifact as _load_artifact,
    save_artifact as _save_artifact,
    save_completed_marker as _save_completed_marker,
    save_failed_marker as _save_failed_marker,
)
from app.features.ocr_alert_rules import evaluate_alerts as _evaluate_alerts
from app.features.question_splitter import split_questions
from app.features.question_type_classifier import detect_options_from_text as _detect_options_from_text
from app.features.similarity_matcher import match_similar_questions
from app.features.structure_analyzer import analyze_structure
from app.features.text_normalizer import ImportTextNormalizer
from app.schemas.import_review import PdfPageRangeInfo
from app.utils.sentry_utils import capture_exception, set_tag, start_span
from app.core.log_context import bind_log_context, log_event, safe_text_preview

# P5-2: extracted stage implementations
from app.features.pipeline_stages.match_stage import run_match_stage
from app.features.pipeline_stages.math_detect_stage import run_math_detect_stage
from app.features.pipeline_stages.normalize_schema_stage import (
    run_batch_dedup_stage,
    run_batch_validation_stage,
    run_normalize_schema_stage,
)
from app.features.pipeline_stages.repair_stage import (
    run_ai_validation_stage,
    run_repair_stage,
)
from app.features.pipeline_stages.code_language_noise_layer import (
    run_code_language_noise_clean_stage,
)
from app.features.pipeline_stages.code_structure_stage import run_code_structure_stage
from app.features.pipeline_stages.review_stage import run_review_stage
from app.features.pipeline_stages.structure_freeze_stage import run_structure_freeze_stage
from app.features.pipeline_stages.table_detect_stage import run_table_detect_stage
from app.features.pipeline_stages._helpers import _log_multi_blank_stage

logger = logging.getLogger(__name__)

# ── Structure Freeze mode ──────────────────────────────────────────────
# Controlled via env var STRUCTURE_FREEZE_MODE.
#   "legacy":    block-based freeze only (current behavior)
#   "dual":      legacy + DocumentIR freeze, compare differences
#   "ir":        DocumentIR freeze as single source of truth
#   "ir_canary": IR-driven freeze with failover to legacy (canary mode)
# ── Structure Freeze mode ──────────────────────────────────────────────
# Check settings first (which loads from .env), fallback to os.environ.
# The accessor functions also serve as cache since _STRUCTURE_FREEZE_MODE
# is read repeatedly during pipelines.
_STRUCTURE_FREEZE_MODE = os.environ.get("STRUCTURE_FREEZE_MODE", "legacy")


def _get_structure_freeze_mode() -> str:
    """Return the effective structure freeze mode, preferring settings."""
    try:
        from app.core.config import settings
        return settings.STRUCTURE_FREEZE_MODE or _STRUCTURE_FREEZE_MODE
    except (ImportError, AttributeError):
        return _STRUCTURE_FREEZE_MODE


# ── Domain Quality Gate mode ──────────────────────────────────────────
# Controlled via env var DOMAIN_QUALITY_GATE_MODE.
#   "off":    not evaluated
#   "shadow": evaluated but does not affect production decisions
#   "enforce": evaluated and can reject
_DOMAIN_QUALITY_GATE_MODE = os.environ.get("DOMAIN_QUALITY_GATE_MODE", "off")


def _get_domain_quality_gate_mode() -> str:
    """Return the effective quality gate mode, preferring settings."""
    try:
        from app.core.config import settings
        return settings.DOMAIN_QUALITY_GATE_MODE or _DOMAIN_QUALITY_GATE_MODE
    except (ImportError, AttributeError):
        return _DOMAIN_QUALITY_GATE_MODE


def _validate_quality_gate_mode(mode: str) -> str:
    """Validate and guard quality gate mode.

    ``enforce`` mode requires ``QUALITY_GATE_ENFORCE_ENABLED=True``
    in settings. Without it, enforce is rejected with a
    ``ConfigurationError`` to prevent accidental enablement.
    """
    if mode == "enforce":
        try:
            from app.core.config import settings
            if not settings.QUALITY_GATE_ENFORCE_ENABLED:
                raise RuntimeError(
                    "DOMAIN_QUALITY_GATE_MODE=enforce is not allowed without "
                    "QUALITY_GATE_ENFORCE_ENABLED=True in settings. "
                    "Set the sentinel explicitly to enable enforce mode."
                )
        except ImportError:
            raise RuntimeError(
                "DOMAIN_QUALITY_GATE_MODE=enforce requires QUALITY_GATE_ENFORCE_ENABLED=True"
            )
    return mode


# Validate on import
_ = _validate_quality_gate_mode(_DOMAIN_QUALITY_GATE_MODE)


def _run_coro_in_loop(coro) -> Any:
    """安全地运行协程，兼容已有或新建事件循环。

    在同步方法中调用异步代码时使用。优先尝试 ``asyncio.run()``，
    RuntimeError（已有事件循环）时回退到 ``new_event_loop``。
    与 ``ocr_service._call_ocr_api`` 的使用模式一致。
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _is_book_import_mode(import_mode) -> bool:
    if isinstance(import_mode, ImportMode):
        return import_mode == ImportMode.BOOK
    return str(import_mode or "").lower() == ImportMode.BOOK.value


_BOOK_PDF_PROSE_MARKER_RE = re.compile(
    r"定义|定理|知识点|证明如下|证毕|解法|例题|例如|如下|因此可得|由此可知|综上|性质|推论|注意|本节|本章|算法|图\s*\d|表\s*\d"
)
_BOOK_PDF_QUESTION_SIGNAL_RE = re.compile(
    r"下列|以下|正确|错误|的是|哪|选择|计算|判断|已知|设|若|试述|简述|回答|为什么|(?:^|[，。；;：:\s])(?:求|问)[：:\s]|\?|？"
)
_BOOK_PDF_SENTENCE_END_RE = re.compile(r"[。；;！!？?]")


def _looks_like_book_pdf_prose_candidate(question: dict) -> bool:
    text = str(question.get("raw_question_text") or "").strip()
    if len(text) < 90:
        return False
    if question.get("has_options") or question.get("option_lines"):
        return False
    marker_count = len(_BOOK_PDF_PROSE_MARKER_RE.findall(text))
    if marker_count < 2:
        return False
    sentence_count = len(_BOOK_PDF_SENTENCE_END_RE.findall(text))
    if sentence_count < 2:
        return False
    if _BOOK_PDF_QUESTION_SIGNAL_RE.search(text):
        return len(text) > 360 and marker_count >= 4 and sentence_count >= 4
    return True


def _apply_frozen_options(
    raw_questions: list[dict],
    frozen_option_registry: dict[str, dict[str, str]],
    freeze_checksum: str | None = None,
    normalized_blocks: list[dict] | None = None,
) -> None:
    """Enrich raw_questions with frozen option data from the freeze stage.

    This is the SINGLE SOURCE OF TRUTH for options. When frozen options
    are found for a question, they REPLACE the option_lines entirely
    (no merge with regex-extracted options). ``is_frozen`` is set to
    ``True`` so downstream stages know not to re-extract or modify
    options.

    Uses exact page + block_index mapping (NO option-value substring matching).
    For each question, determines which normalized blocks it spans by matching
    block text content against the question's raw_text (both from the same
    ``normalized_blocks`` source), then looks up ``page:block_index`` keys
    in the frozen_option_registry.

    Mutates ``raw_questions`` in place.
    """
    if not frozen_option_registry:
        return

    # IMPORT: checksum function at module top (not inline)
    from app.features.pipeline_stages.structure_freeze_stage import (
        _compute_freeze_checksum as _verify_checksum,
    )

    # ── Checksum verification (best-effort, always logged on failure) ──
    if freeze_checksum and len(frozen_option_registry) > 0:
        try:
            _plain: dict = {}
            for _k, _v in frozen_option_registry.items():
                _plain[_k] = dict(_v)
            _actual = _verify_checksum(_plain)
            if _actual != freeze_checksum:
                logger.warning(
                    "[FREEZE] checksum MISMATCH in _apply_frozen_options: "
                    "expected=%s actual=%s — frozen data may have been modified!",
                    freeze_checksum, _actual,
                )
        except Exception as exc:
            logger.warning(
                "[FREEZE] checksum verification failed: %s", exc,
            )

    # ── Build block text index: {page: {block_index: text}} ──
    # Used to map each question to the specific blocks it spans.
    block_index_by_page: dict[int, dict[int, str]] = {}
    if normalized_blocks:
        for b in normalized_blocks:
            p = b.get("page", 0)
            bi = b.get("block_index", 0)
            txt = (b.get("normalized_text") or b.get("text", "")).strip()
            if txt:
                block_index_by_page.setdefault(p, {})[bi] = txt

    applied_count = 0
    for q in raw_questions:
        q_text = q.get("raw_question_text") or ""
        q_page_start = q.get("page_start", 1)
        q_page_end = q.get("page_end", q_page_start)
        if not q_text:
            continue

        # ── Find which blocks this question spans ──
        # For each page in the question's page range, check each block:
        # if the block's text appears in the question's raw_text, that block
        # contributed to this question. This is exact content matching — both
        # come from the same normalized_blocks source.
        question_block_keys: set[str] = set()
        for p in range(q_page_start, q_page_end + 1):
            if p not in block_index_by_page:
                continue
            for bi, block_text in block_index_by_page[p].items():
                registry_key = f"{p}:{bi}"
                if registry_key not in frozen_option_registry:
                    continue  # no frozen options in this block → skip
                if block_text in q_text:
                    question_block_keys.add(registry_key)

        if not question_block_keys:
            continue

        # ── Collect frozen options from matching blocks ──
        frozen_matches: dict[str, str] = {}
        for registry_key in sorted(question_block_keys):
            opts = frozen_option_registry.get(registry_key, {})
            for key, text in opts.items():
                if text and key not in frozen_matches:
                    frozen_matches[str(key)] = str(text)

        if frozen_matches:
            # ── AUTHORITATIVE REPLACEMENT ──
            # Frozen options COMPLETELY REPLACE option_lines. Any options that
            # the freeze stage didn't detect are not included, ensuring zero
            # contamination from regex extraction.
            q["option_lines"] = dict(frozen_matches)
            q["has_options"] = True
            q["is_frozen"] = True
            applied_count += 1
            logger.debug(
                "[FREEZE] applied frozen options to q%s (page %s, blocks=%s): %s",
                q.get("number", "?"), q_page_start,
                sorted(question_block_keys),
                sorted(frozen_matches.keys()),
            )
        elif not q.get("is_frozen"):
            pass

    if applied_count:
        logger.info(
            "[FREEZE] applied frozen options to %d/%d questions",
            applied_count, len(raw_questions),
        )
    elif raw_questions:
        logger.info(
            "[FREEZE] zero questions matched from %d normalized blocks, "
            "%d registry entries, %d raw questions",
            len(normalized_blocks or []),
            len(frozen_option_registry),
            len(raw_questions),
        )


# ---------------------------------------------------------------------------
# DocumentIR helpers for Structure Freeze integration
# ---------------------------------------------------------------------------


def _get_blocks_document_ir(blocks: list[dict]) -> "DocumentIR | None":
    """Get DocumentIR from blocks, building if needed.

    Tries in order:
    1. ``blocks[0]["_document_ir"]`` (set by ``_ocr_scanned_pdf``)
    2. ``get_document_ir(blocks)`` (canonical accessor)
    3. ``_blocks_to_document_ir(blocks)`` (fallback build)

    Returns None when none of the above succeed.
    """
    # 1. Direct reference
    if blocks and blocks[0].get("_document_ir"):
        return blocks[0]["_document_ir"]

    # 2. Canonical accessor
    doc_ir = get_document_ir(blocks)
    if doc_ir is not None:
        return doc_ir

    # 3. Fallback build from blocks
    return _blocks_to_document_ir(blocks)


def _compare_freeze_results(
    legacy_result: dict,
    ir_result: dict,
    legacy_registry: dict[str, dict[str, str]],
    ir_registry: dict[str, list["FrozenOptionEntry"]],
) -> dict:
    """Compare legacy and IR freeze results for dual mode diagnostics.

    Compares at the option level: flattened (key, text) pairs. Also
    reports per-binding differences.

    Returns:
        Diagnostics dict with comparison metrics and difference list.
    """
    # ── Flatten legacy options ──
    legacy_opts: set[tuple[str, str]] = set()
    for _key, opts in legacy_registry.items():
        for k, v in opts.items():
            legacy_opts.add((k, str(v).strip()))

    # ── Flatten IR options ──
    ir_opts: set[tuple[str, str]] = set()
    for _rid, entries in ir_registry.items():
        for entry in entries:
            ir_opts.add((entry.option_key, entry.original_text.strip()))

    # ── Comparison ──
    common = legacy_opts & ir_opts
    only_legacy = legacy_opts - ir_opts
    only_ir = ir_opts - legacy_opts

    differences: list[dict] = []
    for key, text in sorted(only_legacy):
        differences.append({
            "type": "only_in_legacy",
            "option_key": key,
            "legacy_text": text,
            "ir_text": "",
        })
    for key, text in sorted(only_ir):
        differences.append({
            "type": "only_in_ir",
            "option_key": key,
            "ir_text": text,
            "legacy_text": "",
        })

    # ── Text mismatch for shared keys ──
    legacy_by_key: dict[str, str] = {}
    for k, v in legacy_opts:
        legacy_by_key.setdefault(k, v)
    ir_by_key: dict[str, str] = {}
    for k, v in ir_opts:
        ir_by_key.setdefault(k, v)

    text_mismatches = 0
    for k in sorted(set(legacy_by_key.keys()) & set(ir_by_key.keys())):
        lt = legacy_by_key[k].strip()
        it = ir_by_key[k].strip()
        if lt != it:
            text_mismatches += 1
            differences.append({
                "type": "text_mismatch",
                "option_key": k,
                "legacy_text": lt,
                "ir_text": it,
            })

    option_key_match = len(only_legacy) == 0 and len(only_ir) == 0
    option_text_match = text_mismatches == 0

    # ── Binding lost count (IR side) ──
    binding_lost_count = 0
    for _rid, entries in ir_registry.items():
        for entry in entries:
            if entry.binding_status == "binding_lost":
                binding_lost_count += 1

    return {
        "freeze_mode": "dual",
        "legacy_option_count": len(legacy_opts),
        "ir_option_count": len(ir_opts),
        "common_option_count": len(common),
        "option_key_match": option_key_match,
        "option_text_match": option_text_match,
        "binding_lost_count": binding_lost_count,
        "differences_count": len(differences),
        "differences": differences[:50],  # cap at 50 for diagnostics
        "differences_truncated": max(0, len(differences) - 50),
    }


def _safe_hash_preview(data: list[dict]) -> dict:
    """Return a safe (hash + count) summary instead of raw question text."""
    import hashlib
    import json
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return {
        "count": len(data),
        "md5": hashlib.md5(raw.encode()).hexdigest()[:16],
    }


def _safe_text_digest(text: str, max_len: int = 16) -> str:
    """Return a short hash digest instead of raw OCR text."""
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()[:max_len]


def _safe_text_summary(text: str) -> dict:
    """Return a safe summary of text (hash + metrics), never the text itself."""
    import hashlib
    return {
        "len": len(text),
        "nonempty_lines": len([l for l in text.splitlines() if l.strip()]),
        "digest": hashlib.md5(text.encode()).hexdigest()[:12],
    }


def _remap_frozen_registry_vl_rebuild(
    old_registry: dict,
    rebuilt_blocks: list[dict],
) -> dict:
    """Re-map frozen option registry after VL block rebuild.

    Matches frozen options to rebuilt blocks by option key and text content.
    Unmatched options are marked ``binding_lost`` explicitly.

    Returns:
        dict with keys:
        - ``registry``: remapped frozen option registry (same format as input)
        - ``binding_lost_questions``: list[str] of question keys with binding loss
        - ``binding_lost_option_keys``: list[tuple(str,str)] of (qkey, opt_key) with loss
    """
    if not old_registry:
        return {"registry": {}, "binding_lost_questions": [], "binding_lost_option_keys": []}

    # Build a text index of rebuilt blocks: option_key → texts found in block
    rebuilt_texts: dict[str, list[str]] = {}
    for block in rebuilt_blocks:
        text = str(block.get("normalized_text", "") or "")
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Try to extract option key from line ("A. content", "B. content")
            for opt_key in ("A", "B", "C", "D", "E", "F"):
                if line.startswith(f"{opt_key}.") or line.startswith(f"{opt_key}、"):
                    rebuilt_texts.setdefault(opt_key, []).append(line)

    new_registry: dict = {}
    binding_lost_questions: list[str] = []
    binding_lost_option_keys: list[tuple[str, str]] = []

    for question_key, entries in old_registry.items():
        if isinstance(entries, dict):
            # Legacy format: {option_key: text}
            new_opts: dict[str, str] = {}
            lost_keys: list[str] = []
            for opt_key, opt_text in entries.items():
                found = False
                if opt_key in rebuilt_texts:
                    for found_line in rebuilt_texts[opt_key]:
                        if opt_text.strip() in found_line or found_line in opt_text:
                            new_opts[opt_key] = opt_text
                            found = True
                            break
                if not found:
                    # EXPLICIT binding_lost: preserve content but mark as lost
                    new_opts[opt_key] = opt_text
                    lost_keys.append(opt_key)
                    binding_lost_option_keys.append((question_key, opt_key))
            new_registry[question_key] = new_opts
            if lost_keys:
                binding_lost_questions.append(question_key)
        elif isinstance(entries, list):
            # FrozenOptionEntry format
            new_entries = list(entries)
            for entry in new_entries:
                if hasattr(entry, 'binding_status') and getattr(entry, 'binding_status', '') == 'binding_lost':
                    binding_lost_questions.append(question_key)
            new_registry[question_key] = new_entries
        else:
            new_registry[question_key] = entries

    return {
        "registry": new_registry,
        "binding_lost_questions": list(set(binding_lost_questions)),
        "binding_lost_option_keys": list(set(binding_lost_option_keys)),
    }


def _merge_cross_page_blocks(
    blocks: list[dict],
    doc_ir: Any = None,
) -> tuple[list[dict], list[dict], list[str], list[dict]]:
    """Detect cross-page links and merge linked page content into blocks.

    Returns (merged_blocks, cross_page_links, warnings, merge_results).
    merge_results is a list of serialized CrossPageMergeResult dicts.
    """
    warnings: list[str] = []
    cross_page_links: list[dict] = []
    merge_results: list[dict] = []

    if len(blocks) < 2:
        return blocks, cross_page_links, warnings, merge_results

    if doc_ir is None:
        doc_ir = _get_blocks_document_ir(blocks)

    if doc_ir is None or not hasattr(doc_ir, "pages") or not doc_ir.pages:
        return blocks, cross_page_links, warnings, merge_results

    try:
        from app.features.cross_page_linking import detect_cross_page_links

        links = detect_cross_page_links(doc_ir.pages)
        if not links:
            return blocks, cross_page_links, warnings, merge_results

        cross_page_links = [link.to_dict() for link in links]
        if hasattr(doc_ir, "cross_page_links"):
            doc_ir.cross_page_links = cross_page_links

        merged_blocks, merge_results = _apply_cross_page_block_merge(blocks, links, doc_ir)

        logger.info(
            "[CROSS-PAGE] detected %d links, merged across %d pages",
            len(links),
            len(set(l.source_page_id for l in links) | set(l.target_page_id for l in links)),
        )
        return merged_blocks, cross_page_links, warnings, merge_results

    except Exception as exc:
        logger.warning("[CROSS-PAGE] detection failed: %s", exc)
        warnings.append(f"cross_page_error: {exc}")
        return blocks, cross_page_links, warnings, merge_results


def _apply_cross_page_block_merge(
    blocks: list[dict],
    links: list,
    doc_ir: Any,
) -> tuple[list[dict], list[dict]]:
    """Merge cross-page linked content with idempotency and traceability.

    Idempotency: each block tracks its current merge ``_cross_page_revision``.
    If a block already has a revision >= the link's revision, the merge is
    skipped. This prevents duplicate text appending on repeated calls.

    Returns (merged_blocks, merge_results) where merge_results is a list of
    serialized CrossPageMergeResult dicts.
    """
    from app.features.cross_page_linking import CrossPageMergeResult, _get_page_text

    merged = list(blocks)
    merged_pages: set[int] = set()
    merge_results: list[CrossPageMergeResult] = []

    for link_idx, link in enumerate(links):
        source_idx = None
        target_idx = None
        for p in doc_ir.pages:
            pid = getattr(p, "page_id", "")
            pidx = getattr(p, "page_index", -1)
            if pid == link.source_page_id:
                source_idx = pidx
            if pid == link.target_page_id:
                target_idx = pidx

        if source_idx is None or target_idx is None:
            continue
        if link.is_ambiguous:
            continue

        target_page = None
        for p in doc_ir.pages:
            if getattr(p, "page_id", "") == link.target_page_id:
                target_page = p
                break
        if target_page is None:
            continue

        target_text = _get_page_text(target_page)
        if not target_text:
            continue

        source_page_num = source_idx + 1
        link_id = f"{link.source_page_id}->{link.target_page_id}"

        for block in merged:
            if block.get("page") == source_page_num:
                existing = block.get("normalized_text", "") or ""
                block_revision = block.get("_cross_page_revision", 0)

                # Idempotency: skip if already at or above this merge revision
                if block_revision >= link_idx + 1:
                    logger.debug(
                        "[CROSS-PAGE] skip idempotent merge %s (rev=%d >= %d)",
                        link_id, block_revision, link_idx + 1,
                    )
                    break

                # Check if text already present (defense-in-depth)
                if target_text in existing:
                    block_revision = max(block_revision, link_idx + 1)
                    block["_cross_page_revision"] = block_revision
                    logger.debug(
                        "[CROSS-PAGE] text already present, updating revision for %s",
                        link_id,
                    )
                    break

                block["normalized_text"] = existing + "\n" + target_text
                block["_cross_page_revision"] = link_idx + 1
                merged_pages.add(source_page_num)

                # Build merge result for traceability
                source_region_ids: list[str] = []
                if hasattr(doc_ir.pages[source_idx], "regions"):
                    source_region_ids = [
                        getattr(r, "region_id", "") for r in doc_ir.pages[source_idx].regions
                    ]
                merge_result = CrossPageMergeResult(
                    merged_block_id=f"{link.source_page_id}:block_{source_page_num}",
                    source_block_ids=[str(block.get("block_index", ""))],
                    source_page_ids=[link.source_page_id],
                    source_region_ids=source_region_ids + list(link.source_region_ids),
                    applied_link_ids=[link_id],
                    revision=link_idx + 1,
                    link_confidence=link.confidence,
                    reason_codes=list(link.reason_codes),
                )
                merge_results.append(merge_result)
                logger.debug(
                    "[CROSS-PAGE] merged %s → p%d (rev=%d, conf=%.2f, reasons=%s)",
                    link_id, source_page_num, link_idx + 1,
                    link.confidence, link.reason_codes,
                )
                break

    if merged_pages:
        logger.info(
            "[CROSS-PAGE] merged content into pages %s (%d merge results)",
            sorted(merged_pages), len(merge_results),
        )

    return merged, [r.to_dict() for r in merge_results]


# ---------------------------------------------------------------------------
# in-memory pipeline state store
# ---------------------------------------------------------------------------

_pipeline_store: dict[str, dict] = {}
_pipeline_diagnostics_store: dict[str, dict] = {}
_ocr_progress: dict[str, str] = {}  # pipeline_id -> "32/312 pages"

_MAX_STORE_SIZE = 500  # keep at most N pipelines in memory
_MAX_DIAGNOSTICS_SIZE = 100  # keep at most N diagnostics snapshots in memory
_PIPELINE_REDIS_PREFIX = "import:pipeline"
_PIPELINE_DIAGNOSTICS_REDIS_PREFIX = "import:pipeline:diagnostics"
_PIPELINE_STATUS_TTL = 86400  # 24h
# P3-2: per-stage checkpoint (lightweight, only completed stage names + small metadata)
# Key: pipeline_id, Value: dict with completed_stages, current_stage, diagnostics, etc.
_CHECKPOINT_REDIS_PREFIX = "import:pipeline:stage_ckpt"
_CHECKPOINT_TTL = 86400  # 24h — same as pipeline status

# P4: 主 store 只保留这些瘦身字段；diagnostics 等大对象走独立 KV。
# raw_questions_preview 已替换为 _safe_hash_preview。no raw text in store.
_PIPELINE_STORE_FIELDS = (
    "pipeline_id",
    "status",
    "source_type",
    "source_file",
    "current_stage",
    "stages",
    "stats",
    "errors",
    "started_at",
    "finished_at",
    "batch_id",
    "question_count",
    "quality_report",
    "artifacts",
    "page_range",
    "_file_path",
)


def _prune_store() -> None:
    """Remove oldest entries when store exceeds max size."""
    if len(_pipeline_store) > _MAX_STORE_SIZE:
        sorted_ids = sorted(
            _pipeline_store.keys(),
            key=lambda k: _pipeline_store[k].get("started_at", ""),
        )
        for old_id in sorted_ids[: len(_pipeline_store) - _MAX_STORE_SIZE]:
            _pipeline_store.pop(old_id, None)
            _pipeline_diagnostics_store.pop(old_id, None)


def _prune_diagnostics_store() -> None:
    """Prune diagnostics store independently from main store.

    Diagnostics entries lack started_at timestamps; evict oldest by
    insertion order which is a reasonable heuristic.
    """
    if len(_pipeline_diagnostics_store) > _MAX_DIAGNOSTICS_SIZE:
        excess = len(_pipeline_diagnostics_store) - _MAX_DIAGNOSTICS_SIZE
        for key in list(_pipeline_diagnostics_store.keys())[:excess]:
            _pipeline_diagnostics_store.pop(key, None)


# P3-2: per-stage checkpoint store — lightweight, only stage names + small metadata
_pipeline_stage_checkpoints: dict[str, dict] = {}
_MAX_STAGE_CKPT_SIZE = 200


def _prune_stage_checkpoints() -> None:
    """Evict oldest stage checkpoints by insertion order."""
    if len(_pipeline_stage_checkpoints) > _MAX_STAGE_CKPT_SIZE:
        excess = len(_pipeline_stage_checkpoints) - _MAX_STAGE_CKPT_SIZE
        for key in list(_pipeline_stage_checkpoints.keys())[:excess]:
            _pipeline_stage_checkpoints.pop(key, None)


async def _write_stage_checkpoint(
    pipeline_id: str,
    *,
    completed_stages: list[str],
    current_stage: str,
    stage_statuses: dict,
    failed_stage: str | None = None,
    error: str | None = None,
    source_type: str | None = None,
    source_file: str | None = None,
    subject: str | None = None,
    options: dict | None = None,
) -> None:
    """Write lightweight per-stage checkpoint after each stage completes/fails.

    Only small metadata is stored — no large stage outputs. The checkpoint
    serves to track progress and enable resume (which re-derives large data
    from the source file).
    """
    ckpt: dict = {
        "completed_stages": completed_stages,
        "current_stage": current_stage,
        "stage_statuses": stage_statuses,
        "failed_stage": failed_stage,
        "error": error,
        "source_type": source_type,
        "source_file": source_file,
        "subject": subject,
        "options": options,
        "updated_at": datetime.now().isoformat(),
    }
    # Strip large fields to keep checkpoint lightweight
    if "stage_statuses" in ckpt and ckpt["stage_statuses"]:
        ckpt["stage_statuses"] = {
            k: {"status": v.get("status"), "duration_ms": v.get("duration_ms"),
                "error": v.get("error")}
            for k, v in ckpt["stage_statuses"].items()
            if isinstance(v, dict)
        }
    _pipeline_stage_checkpoints[pipeline_id] = ckpt
    _prune_stage_checkpoints()
    try:
        from app.core.cache import cache
        await cache.set(
            f"{_CHECKPOINT_REDIS_PREFIX}:{pipeline_id}",
            ckpt,
            ttl=_CHECKPOINT_TTL,
        )
    except Exception:
        pass


async def _get_stage_checkpoint(pipeline_id: str) -> dict | None:
    """Read per-stage checkpoint from memory or Redis. Returns None if missing."""
    if pipeline_id in _pipeline_stage_checkpoints:
        return _pipeline_stage_checkpoints[pipeline_id]
    try:
        from app.core.cache import cache
        data = await cache.get(f"{_CHECKPOINT_REDIS_PREFIX}:{pipeline_id}")
        if data:
            _pipeline_stage_checkpoints[pipeline_id] = data
            return data
    except Exception:
        pass
    return None


async def _clear_stage_checkpoint(pipeline_id: str) -> None:
    """Remove checkpoint — called when pipeline completes successfully."""
    _pipeline_stage_checkpoints.pop(pipeline_id, None)
    try:
        from app.core.cache import cache
        await cache.delete(f"{_CHECKPOINT_REDIS_PREFIX}:{pipeline_id}")
    except Exception:
        pass


def _slim_ocr_diagnostics(diag: dict) -> dict:
    """Truncate large arrays in OCR diagnostics to bound memory."""
    if not diag:
        return diag
    corrections = diag.get("corrections", [])
    if len(corrections) > 50:
        diag = {**diag, "corrections": corrections[:50],
                "corrections_truncated": len(corrections) - 50}
    return diag


def _slim_value(value: Any) -> Any:
    """Pass through non-None values; avoid polluting diagnostics with None."""
    return value if value is not None else {}


def _summarize_ocr_diffs(corrections: list[dict]) -> dict:
    """Summarize OCR correction diffs for diagnostics stage_diffs."""
    corrected = [c for c in corrections if c.get("corrected")]
    rejected = [c for c in corrections if c.get("reason", "").startswith("safety_rejected")]
    all_safety = [c["safety"] for c in corrections if c.get("safety")]
    return {
        "total_corrected": len(corrected),
        "safety_rejected": len(rejected),
        "models_used": list({c.get("model_used", "unknown") for c in corrected}),
        "risk_flags": list({f for s in all_safety for f in s.get("risk_flags", [])}),
        "details": corrected[:30],  # cap at 30 to bound diagnostics
    }


def _slim_pipeline_payload(data: dict) -> dict:
    """仅保留 _PIPELINE_STORE_FIELDS 中存在于 data 的字段。

    避免把 diagnostics / 大 result 字段写进主 store。
    """
    return {k: data[k] for k in _PIPELINE_STORE_FIELDS if k in data}


async def _set_pipeline_diagnostics(pipeline_id: str, diagnostics: dict) -> None:
    """diagnostics 单独存（主 store 之外）。"""
    if not diagnostics:
        return
    _pipeline_diagnostics_store[pipeline_id] = diagnostics
    _prune_diagnostics_store()
    try:
        from app.core.cache import cache
        await cache.set(
            f"{_PIPELINE_DIAGNOSTICS_REDIS_PREFIX}:{pipeline_id}",
            diagnostics,
            ttl=_PIPELINE_STATUS_TTL,
        )
    except Exception:
        pass


async def _get_pipeline_diagnostics(pipeline_id: str) -> dict | None:
    if pipeline_id in _pipeline_diagnostics_store:
        return _pipeline_diagnostics_store[pipeline_id]
    try:
        from app.core.cache import cache
        data = await cache.get(f"{_PIPELINE_DIAGNOSTICS_REDIS_PREFIX}:{pipeline_id}")
        if data:
            _pipeline_diagnostics_store[pipeline_id] = data
            return data
    except Exception:
        pass
    return None


async def _set_pipeline_store(pipeline_id: str, data: dict) -> None:
    """写入流水线状态。

    P0-3: data 中如果含 diagnostics，会被剥离到独立 KV；主 store 仅保留
    _PIPELINE_STORE_FIELDS 字段。前端通过 get_pipeline_status 拿到的
    视图与改造前一致（diagnostics 合并回去）。

    当 pipeline 进入终态 (completed/failed) 时，自动从 in-memory store 中
    移除以控制内存增长。Redis 中的状态仍保留 24h，SSE 轮询可通过 Redis 读取。
    """
    diagnostics = data.get("diagnostics")
    slim = _slim_pipeline_payload(data)
    _pipeline_store[pipeline_id] = slim
    _prune_store()
    try:
        from app.core.cache import cache
        await cache.set(
            f"{_PIPELINE_REDIS_PREFIX}:{pipeline_id}", slim, ttl=_PIPELINE_STATUS_TTL,
        )
    except Exception:
        pass
    if diagnostics:
        await _set_pipeline_diagnostics(pipeline_id, diagnostics)
    # 不主动 evict 终态条目——SSE 轮询需要持续读取结果。
    # 内存由 _prune_store 的 LRU 上限控制，终态条目自然老化后被淘汰。


def _evict_pipeline_store(pipeline_id: str) -> None:
    """从 in-memory 存储中移除 pipeline 条目。

    幂等操作；Redis 中的缓存不会被删除，SSE/轮询可通过 Redis 继续读取。
    """
    _pipeline_store.pop(pipeline_id, None)
    _pipeline_diagnostics_store.pop(pipeline_id, None)
    _ocr_progress.pop(pipeline_id, None)


async def _get_pipeline_store(pipeline_id: str) -> dict | None:
    if pipeline_id in _pipeline_store:
        return _pipeline_store[pipeline_id]
    try:
        from app.core.cache import cache
        data = await cache.get(f"{_PIPELINE_REDIS_PREFIX}:{pipeline_id}")
        if data:
            _pipeline_store[pipeline_id] = data
            return data
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def _open_pdf_doc(source: bytes | str | os.PathLike):
    """统一打开 PDF：bytes 走 stream，path 走 filename。

    传 path 时 PyMuPDF 通过 mmap 加载，避免把整文件复制到 Python heap，
    显著降低 100~400 MB 大文件的内存占用 (P0-1)。
    """
    import fitz

    if isinstance(source, (str, os.PathLike)):
        return fitz.open(str(source), filetype="pdf")
    return fitz.open(stream=source, filetype="pdf")


def _extract_pdf_blocks(
    content_or_path: bytes | str,
    page_start: int = 1,
    page_end: int | None = None,
) -> list[dict]:
    """Extract text blocks from PDF using PyMuPDF.

    Returns list of {page, block_index, text} for use as raw_blocks input
    to ImportTextNormalizer.

    P0-1: content_or_path 接受 bytes 或文件路径，路径优先（mmap）。
    """
    try:
        import fitz  # noqa: F401  (used inside _open_pdf_doc)
    except ImportError:
        raise RuntimeError("PyMuPDF (fitz) 未安装，无法提取 PDF 文本")

    doc = _open_pdf_doc(content_or_path)
    total_pages = len(doc)
    start_idx = max(0, (page_start or 1) - 1)
    end_idx = min(total_pages, page_end or total_pages)

    blocks: list[dict] = []
    try:
        for i in range(start_idx, end_idx):
            text = doc[i].get_text()
            if text.strip():
                blocks.append({
                    "page": i + 1,
                    "block_index": len(blocks),
                    "text": text.strip(),
                })
    finally:
        doc.close()

    return blocks


def _render_page_images(
    *,
    file_content: bytes | None = None,
    file_path: str | None = None,
    source_type: str = "pdf",
    max_dimension: int = 2048,
    page_start: int = 1,
    page_end: int | None = None,
) -> dict[int, bytes] | None:
    """Render PDF pages to PNG images keyed by page number (1-based).

    Only renders when source is PDF and content/path is available.
    Images are limited to *max_dimension* on the longest side.
    Returns None for non-PDF sources or when rendering fails.
    """
    if source_type != "pdf":
        return None

    pdf_source = file_path or file_content
    if pdf_source is None:
        return None

    try:
        import fitz

        doc = fitz.open(pdf_source) if isinstance(pdf_source, str) else fitz.open(stream=pdf_source, filetype="pdf")
        total_pages = len(doc)
        start_idx = max(0, (page_start or 1) - 1)
        end_idx = min(total_pages, page_end or total_pages)

        page_images: dict[int, bytes] = {}
        try:
            for i in range(start_idx, end_idx):
                page = doc[i]
                dpi = 150
                pix = page.get_pixmap(dpi=dpi)
                png = pix.tobytes("png")
                # Resize if exceeds max dimension
                if max(pix.width, pix.height) > max_dimension:
                    scale = max_dimension / max(pix.width, pix.height)
                    pix = page.get_pixmap(dpi=int(dpi * scale))
                    png = pix.tobytes("png")
                page_images[i + 1] = png
        finally:
            doc.close()
        return page_images
    except Exception:
        return None


def _render_page_image_refs(
    file_path: str | None,
    temp_dir: str,
    source_type: str = "pdf",
    max_dimension: int = 2048,
    page_start: int = 1,
    page_end: int | None = None,
) -> dict[int, str] | None:
    """P2-2: 渲染 PDF 页为 PNG 并写入临时文件，返回 {page_num: filepath}。

    与 _render_page_images 功能相同但输出为文件路径而非 bytes。
    供 math_detect stage 用于公式截图裁剪。
    """
    if source_type != "pdf" or not file_path:
        return None

    try:
        import fitz

        doc = fitz.open(file_path, filetype="pdf")
        total_pages = len(doc)
        start_idx = max(0, (page_start or 1) - 1)
        end_idx = min(total_pages, page_end or total_pages)

        refs: dict[int, str] = {}
        try:
            for i in range(start_idx, end_idx):
                page = doc[i]
                dpi = 150
                pix = page.get_pixmap(dpi=dpi)
                if max(pix.width, pix.height) > max_dimension:
                    scale = max_dimension / max(pix.width, pix.height)
                    pix = page.get_pixmap(dpi=int(dpi * scale))
                png_path = os.path.join(temp_dir, f"page_{i + 1}.png")
                pix.save(png_path)
                refs[i + 1] = png_path
        finally:
            doc.close()
        return refs
    except Exception as e:
        logger.warning("page image refs render failed: %s", e)
        return None


def _ocr_scanned_pdf(
    content_or_path: bytes | str,
    pipeline_id: str = "",
    page_start: int = 1,
    page_end: int | None = None,
) -> list[dict]:
    """用 PaddleOCR 识别扫描版 PDF 各页。

    分批并发处理，每批 OCR 后释放图像内存以避免累积 OOM。
    超过 MAX_OCR_PAGES 截断，超过 OCR_TIMEOUT_SECONDS 超时中断。
    输出格式：[{page, block_index, text, boxes, page_width, page_height}]
    boxes 为每行的 bbox 坐标和置信度，供后续预处理使用。

    P0-1: content_or_path 接受 bytes 或文件路径，路径优先 (mmap)。
    """
    import gc
    import time

    import fitz  # noqa: F401

    from app.core.config import settings
    from app.core.ocr_profile import get_ocr_profile
    from app.services.ocr_service import ocr_pages, ocr_pages_with_boxes

    profile = get_ocr_profile()
    max_pages = settings.MAX_OCR_PAGES
    timeout = profile.timeout_seconds
    batch_size = profile.max_workers

    doc = _open_pdf_doc(content_or_path)
    total_pages = len(doc)

    # Sentry OCR monitoring
    set_tag("ocr.engine", "PaddleOCR")
    ocr_source = str(content_or_path) if isinstance(content_or_path, (str, os.PathLike)) else pipeline_id
    set_tag("ocr.source", ocr_source[:200])

    # Page range: convert 1-based user params to 0-based indices
    start_idx = max(0, (page_start or 1) - 1)
    end_idx = min(total_pages, page_end or total_pages)
    pages_in_range = end_idx - start_idx
    pages_to_process = min(pages_in_range, max_pages) if max_pages > 0 else pages_in_range

    blocks: list[dict] = []
    page_dimensions: dict[int, tuple[int, int]] = {}
    ocr_text_fallback_unavailable_pages: set[int] = set()
    timed_out = False
    start_time = time.monotonic()

    logger.info("OCR 开始：共 %d 页待处理（第 %d-%d 页）", pages_to_process, start_idx + 1, end_idx)
    if pipeline_id:
        _ocr_progress[pipeline_id] = f"0/{pages_to_process} pages"

    try:
        for batch_start in range(0, pages_to_process, batch_size):
            elapsed = time.monotonic() - start_time
            if timeout > 0 and elapsed >= timeout:
                logger.warning(
                    "OCR 超时中断：已用 %.1fs（限制 %ds），处理了 %d/%d 页",
                    elapsed, timeout, batch_start, pages_to_process,
                )
                timed_out = True
                break

            batch_end = min(batch_start + batch_size, pages_to_process)
            batch_images: list[tuple[int, bytes]] = []

            for i in range(batch_start, batch_end):
                page_idx = start_idx + i
                pix = doc[page_idx].get_pixmap(dpi=150)
                png_bytes = pix.tobytes("png")
                page_dimensions[page_idx + 1] = (pix.width, pix.height)
                del pix
                batch_images.append((page_idx + 1, png_bytes))

            results = ocr_pages_with_boxes(batch_images, skip_rotation=True)
            batch_image_map = {idx: png for idx, png in batch_images}
            failed_images = [
                (idx, batch_image_map[idx])
                for idx, result in results.items()
                if result.failed and idx in batch_image_map
            ]
            try:
                # Reset OCR before text fallback to avoid using corrupted model state
                from app.services.ocr_service import reset_ocr_engine
                reset_ocr_engine()
                fallback_results = ocr_pages(failed_images) if failed_images else {}
            except (RuntimeError, Exception) as exc:
                logger.warning("OCR text fallback failed: %s — retrying with another reset", exc)
                try:
                    reset_ocr_engine()
                    fallback_results = ocr_pages(failed_images) if failed_images else {}
                except Exception as exc2:
                    logger.warning("OCR text fallback retry also failed: %s", exc2)
                    fallback_results = {}
                    ocr_text_fallback_unavailable_pages.update(idx for idx, _ in failed_images)

            del batch_images
            gc.collect()

            for page_idx in sorted(results.keys()):
                result = results[page_idx]
                pw, ph = page_dimensions[page_idx]
                if result.failed:
                    text = fallback_results.get(page_idx, "")
                    if text.strip():
                        blocks.append({
                            "page": page_idx,
                            "page_index": page_idx,
                            "block_index": len(blocks),
                            "text": text,
                            "boxes": [],
                            "page_width": pw,
                            "page_height": ph,
                            "source": "ocr_text_fallback",
                            "has_boxes": False,
                            "_ocr_boxes_failed": True,
                        })
                    else:
                        ocr_text_fallback_unavailable_pages.add(page_idx)
                    continue

                text = result.text
                if text.strip():
                    boxes = result.boxes or []
                    blocks.append({
                        "page": page_idx,
                        "page_index": page_idx,
                        "block_index": len(blocks),
                        "text": text,
                        "boxes": boxes,
                        "page_width": pw,
                        "page_height": ph,
                        "source": "ocr_boxes",
                        "has_boxes": bool(boxes),
                    })

            logger.info(
                "OCR 进度：%d/%d 页已处理（%.1fs）",
                batch_end, pages_to_process, time.monotonic() - start_time,
            )
            if pipeline_id:
                _ocr_progress[pipeline_id] = f"{batch_end}/{pages_to_process} pages"
    finally:
        doc.close()

    if timed_out and blocks:
        blocks[0].setdefault("_warnings", [])
        blocks[0]["_warnings"].append(
            f"ocr_timeout: processed {len(blocks)} blocks in {timeout}s limit"
        )
    elif max_pages > 0 and pages_in_range > max_pages and blocks:
        blocks[0].setdefault("_warnings", [])
        blocks[0]["_warnings"].append(
            f"ocr_pages_truncated: processed {pages_to_process}/{pages_in_range} selected pages"
        )

    if ocr_text_fallback_unavailable_pages and blocks:
        pages = sorted(ocr_text_fallback_unavailable_pages)
        blocks[0]["_ocr_text_fallback_unavailable_pages"] = pages
        blocks[0]["_ocr_runtime_failed_pages"] = pages

    if pipeline_id:
        _ocr_progress.pop(pipeline_id, None)

    # Build Document IR from OCR blocks for downstream consumption
    doc_ir = _blocks_to_document_ir(blocks, pipeline_id=pipeline_id)
    if doc_ir and blocks:
        blocks[0]["_document_ir"] = doc_ir

    # Sentry OCR summary
    ocr_duration = time.monotonic() - start_time
    set_tag("ocr.pages_total", pages_to_process)
    set_tag("ocr.pages_processed", len(set(b.get("page") for b in blocks)))
    set_tag("ocr.blocks", len(blocks))
    set_tag("ocr.duration_ms", int(ocr_duration * 1000))
    if timed_out:
        set_tag("ocr.timed_out", True)
    failed_count = len(ocr_text_fallback_unavailable_pages)
    if failed_count:
        set_tag("ocr.failed_pages", failed_count)

    return blocks


def _blocks_to_document_ir(
    blocks: list[dict],
    *,
    pipeline_id: str = "",
    engine: str = "paddleocr",
    source_bytes: bytes | None = None,
) -> "DocumentIR | None":
    """Convert OCR blocks into a DocumentIR.

    Delegates to ``document_ir_builder.blocks_to_document_ir()``.
    Kept as thin wrapper for backward compat.
    """
    from app.features.document_ir_builder import blocks_to_document_ir as _builder
    return _builder(blocks, pipeline_id=pipeline_id, engine=engine, source_bytes=source_bytes)


# ---------------------------------------------------------------------------
# Document IR — first-class access API
# ---------------------------------------------------------------------------


def get_document_ir(blocks: list[dict]) -> "DocumentIR | None":
    """Retrieve the DocumentIR from OCR blocks, if available.

    This is the canonical way for downstream consumers to access the
    structured OCR result. Returns None when the IR was not built
    (e.g. legacy pipeline paths).

    Example::

        doc_ir = get_document_ir(blocks)
        if doc_ir:
            for page in doc_ir.pages:
                for region in page.regions:
                    process(region)
    """
    if not blocks:
        return None
    return blocks[0].get("_document_ir")


def document_ir_to_json(doc_ir: "DocumentIR") -> dict:
    """Serialize DocumentIR to a JSON-compatible dict.

    Uses ``app.core.document_ir.document_ir_to_dict`` when available.
    Falls back to an empty dict on import failure.
    """
    try:
        from app.core.document_ir import document_ir_to_dict
        return document_ir_to_dict(doc_ir)
    except ImportError:
        return {}


def document_ir_from_json(data: dict) -> "DocumentIR | None":
    """Deserialize a dict back to DocumentIR.

    Uses ``app.core.document_ir.document_ir_from_dict`` when available.
    Returns None on import failure.
    """
    try:
        from app.core.document_ir import document_ir_from_dict
        return document_ir_from_dict(data)
    except ImportError:
        return None


def _extract_page_texts_from_blocks(blocks: list[dict]) -> dict[int, str]:
    """Extract per-page concatenated text from full OCR blocks.

    Used by exercise detection to reuse the single full OCR pass instead of
    running a separate lightweight OCR scan.
    """
    page_texts: dict[int, str] = {}
    for block in blocks:
        page = block.get("page", 0)
        text = block.get("text", "")
        if not text.strip():
            continue
        if page not in page_texts:
            page_texts[page] = text
        else:
            page_texts[page] += "\n" + text
    return page_texts


_BINARY_MAGIC_BYTES: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"RIFF", "WebP"),  # RIFF + "WEBP" at offset 8
    (b"%PDF", "PDF"),
]


def _detect_binary_header(data: bytes) -> str | None:
    """Check if *data* starts with a known image/document magic number.

    Returns the format name (e.g. "PNG", "JPEG") or None if no match.
    """
    for magic, fmt in _BINARY_MAGIC_BYTES:
        if data.startswith(magic):
            return fmt
    # WebP specific: check offset 8
    if data.startswith(b"RIFF") and len(data) > 12 and data[8:12] == b"WEBP":
        return "WebP"
    return None


def _extract_text_blocks(content_or_path: bytes | str) -> list[dict]:
    """Extract text blocks from plain text content.

    P0-1: 接受 bytes 或文件路径。
    防御：自动检测 PNG/JPEG/GIF/WebP/PDF 等二进制文件头，避免静默污染。
    """
    if isinstance(content_or_path, (str, os.PathLike)):
        with open(content_or_path, "rb") as f:
            content = f.read()
    else:
        content = content_or_path
    fmt = _detect_binary_header(content)
    if fmt:
        raise ValueError(
            f"不是文本文件：检测到 {fmt} 格式内容（file_path={content_or_path})。"
            "图片导入应使用 OCR 后的 file_content，而非原始图片文件路径。"
        )
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("文本内容为空")
    return [{"page": 1, "block_index": 0, "text": text}]


# ---------------------------------------------------------------------------
# P2-2 chunk planning helpers
# ---------------------------------------------------------------------------


_DEFAULT_CHUNK_SIZE = 40


def _resolve_chunk_size() -> int:
    """Read chunk size from env, default 40. 0 disables chunking.

    When ``PDF_RENDER_PAGE_WINDOW > 0`` and is smaller than the env value,
    the page window becomes the effective chunk size (ensures rendered pages
    fit within the memory budget).
    """
    from app.core.config import settings

    page_window = settings.PDF_RENDER_PAGE_WINDOW
    raw = os.environ.get("IMPORT_PIPELINE_CHUNK_SIZE")
    if raw is None:
        env_size = _DEFAULT_CHUNK_SIZE
    else:
        try:
            env_size = int(raw)
        except ValueError:
            env_size = _DEFAULT_CHUNK_SIZE

    if page_window > 0 and page_window < env_size:
        logger.info(
            "Chunk size capped by PDF_RENDER_PAGE_WINDOW=%d (env value was %d)",
            page_window, env_size,
        )
        return page_window
    return env_size


_DEFAULT_CHUNK_OVERLAP = 3


def _resolve_chunk_overlap() -> int:
    """Read chunk-overlap pages from env, default 3. 0 disables overlap."""
    raw = os.environ.get("IMPORT_PIPELINE_CHUNK_OVERLAP")
    if raw is None:
        return _DEFAULT_CHUNK_OVERLAP
    try:
        val = int(raw)
        return max(0, val)
    except ValueError:
        return _DEFAULT_CHUNK_OVERLAP


def _split_into_chunks(total_pages: int, chunk_size: int) -> list[tuple[int, int]]:
    """Split page count into 1-based closed intervals [(start, end), ...].

    Example: total_pages=100, chunk_size=40 → [(1,40), (41,80), (81,100)].
    """
    if total_pages <= 0 or chunk_size <= 0:
        return []
    ranges: list[tuple[int, int]] = []
    start = 1
    while start <= total_pages:
        end = min(start + chunk_size - 1, total_pages)
        ranges.append((start, end))
        start = end + 1
    return ranges


def resolve_pdf_page_range(
    total_pages: int,
    page_start: int | None = None,
    page_end: int | None = None,
) -> PdfPageRangeInfo:
    """Validate and resolve PDF page range to effective start/end.

    Rules:
        page_start defaults to 1
        page_end defaults to total_pages
        Both are inclusive (1-based physical page numbers).

    Raises ValueError with user-readable messages on invalid ranges.
    """
    if total_pages < 1:
        raise ValueError("PDF 总页数无效")

    requested_start = page_start
    requested_end = page_end

    if page_start is not None:
        if not isinstance(page_start, int) or page_start < 1:
            raise ValueError("起始页必须是大于等于 1 的整数")
        if page_start > total_pages:
            raise ValueError(f"起始页 {page_start} 超出 PDF 总页数 {total_pages}")

    if page_end is not None:
        if not isinstance(page_end, int) or page_end < 1:
            raise ValueError("结束页必须是大于等于 1 的整数")
        if page_end > total_pages:
            raise ValueError(f"结束页 {page_end} 超出 PDF 总页数 {total_pages}")

    effective_start = page_start or 1
    effective_end = page_end or total_pages

    if effective_start > effective_end:
        raise ValueError("起始页不能大于结束页")

    selected_page_count = effective_end - effective_start + 1

    return PdfPageRangeInfo(
        requested_start=requested_start,
        requested_end=requested_end,
        effective_start=effective_start,
        effective_end=effective_end,
        selected_page_count=selected_page_count,
        total_pages=total_pages,
    )


def split_page_range(
    start_page: int,
    end_page: int,
    chunk_size: int,
) -> list[tuple[int, int]]:
    """Split a page range into 1-based closed-interval chunks.

    Example: start=101, end=220, chunk_size=40
             → [(101, 140), (141, 180), (181, 220)]
    """
    if start_page < 1 or end_page < start_page or chunk_size <= 0:
        return []
    ranges: list[tuple[int, int]] = []
    current = start_page
    while current <= end_page:
        chunk_end = min(current + chunk_size - 1, end_page)
        ranges.append((current, chunk_end))
        current = chunk_end + 1
    return ranges


def _read_pdf_page_count(source: bytes | str | None) -> int:
    """Open the PDF just long enough to read len(doc); close immediately."""
    if source is None:
        return 0
    doc = _open_pdf_doc(source)
    try:
        return len(doc)
    finally:
        doc.close()


def _compute_overlap_hash(raw_question: dict) -> str | None:
    """P1-3: 把 split 阶段的原始题目 dict 折算成稳定的 overlap-dedup key。

    复用 ``QuestionNormalizer`` 的口径（去除空白/控制字符 + 选项排序），
    保证同一物理题在两个 chunk 里折出同一个 hash，OCR 把 ``1`` 误识成 ``I``
    或截留前缀页码不再影响判断。

    与 ``review_service.build_question_hash`` 的差别：split 阶段没有匹配到
    答案，因此 answer 端始终为空——这只影响 hash 值本身、不影响稳定性，
    且 chunk 间 overlap 的同一物理题答案侧也都为空，仍然命中。

    返回 None 表示题干和选项都为空（异常 OCR），调用方按"无 hash"处理，
    保留 P2-3 兜底（page_start>logical_end 时仍按 number 兜底丢弃）。
    """
    from app.features.question_normalizer import _extract_stem
    from app.features.question_pipeline import QuestionNormalizer

    raw_text = raw_question.get("raw_question_text") or ""
    option_lines = raw_question.get("option_lines") or {}

    stem = _extract_stem(str(raw_text), option_lines)
    if not stem and not option_lines:
        return None

    normalizer = QuestionNormalizer()
    return normalizer.build_question_hash(stem, option_lines, None) or None


def _serialize_watermark_patterns(patterns: list) -> list[dict]:
    """P0-3: 把已编译的 ``re.Pattern`` 列表转成 JSON 可序列化的快照。

    每条记录保留 pattern 源字符串与 flags，足以在 resume 时重建出
    与首次导入字节级一致的 ``re.Pattern``。非 Pattern 对象保守地
    跳过——load_rules 偶发 fallback 路径理论上不会混入异类。
    """
    out: list[dict] = []
    for pat in patterns or []:
        try:
            out.append({"pattern": pat.pattern, "flags": int(pat.flags)})
        except AttributeError:
            # 兜底：dict 形式直接收，字符串当 pattern
            if isinstance(pat, dict) and "pattern" in pat:
                out.append({"pattern": pat["pattern"], "flags": int(pat.get("flags", 0))})
            elif isinstance(pat, str):
                out.append({"pattern": pat, "flags": 0})
    return out


def _deserialize_watermark_patterns(snapshot: list | dict | None) -> list:
    """P0-3: 把 watermark_snapshot JSON 反序列化回 ``re.Pattern`` 列表。

    snapshot 损坏 / 元素无法编译时跳过该条而不抛错——首次导入时已通过
    ``_validate_pattern`` 校验，这里属于纵深防御。
    """
    if not snapshot:
        return []
    items = snapshot if isinstance(snapshot, list) else [snapshot]
    compiled: list = []
    for item in items:
        if not isinstance(item, dict):
            continue
        src = item.get("pattern")
        if not isinstance(src, str):
            continue
        flags = item.get("flags") or 0
        try:
            compiled.append(re.compile(src, int(flags)))
        except re.error:
            continue
    return compiled


def _derive_session_factory(db):
    """P0-3: 从一个已有的 ``AsyncSession`` 推导出 sessionmaker，便于 chunk
    循环里开"独立 session、独立事务"的子上下文。

    生产路径：``imports.py`` 用全局 ``async_session()`` 开 session 后传入，
    ``db.bind`` 即全局 engine，等价于直接拿全局工厂。
    测试路径：测试用 tmp_path SQLite 建独立 engine + sessionmaker，传入的
    ``db`` 绑到该 engine，从这里派生出的工厂指向同一个 DB，避免污染全局。

    任何异常 / db 为 None 时回退到全局 ``async_session``，保留向后兼容。
    """
    from app.core.database import async_session as _global_async_session

    if db is None:
        return _global_async_session
    try:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        bind = getattr(db, "bind", None)
        if bind is None:
            return _global_async_session
        return async_sessionmaker(bind, expire_on_commit=False, class_=AsyncSession)
    except Exception:
        logger.debug("derive session factory failed; using global async_session", exc_info=True)
        return _global_async_session


def _build_stats(data: dict, stages: dict) -> dict:
    """Aggregate per-stage outputs into the legacy stats dict."""
    return {
        "total": data.get("extracted", 0),
        "extracted": data.get("extracted", 0),
        "normalized": data.get(
            "normalized_count",
            data.get("normalized_block_count", 0),
        ),
        "analyzed": data.get("split_count", len(data.get("raw_questions", []))),
        "split": data.get("split_count", 0),
        "matched": data.get("matched_count", 0),
        "schema_normalized": data.get("normalized_count", 0),
        "missing_options": sum(
            1
            for q in data.get("questions", [])
            if "missing_options" in q.get("errors", [])
        ),
        "repaired": data.get("repaired_count", 0),
        "to_review": data.get("written", 0),
        "failed": sum(1 for s in stages.values() if s.status == "failed"),
    }


def _build_diagnostics(data: dict, stages: dict | None = None) -> dict:
    mode = data.get("import_mode", ImportMode.AUTO)
    raw = {
        "import_mode": mode.value if hasattr(mode, "value") else str(mode),
        "exercise_regions": data.get("exercise_regions", []),
        "exercise_regions_missing": bool(data.get("exercise_regions_missing")),
        "structure": data.get("structure", {}),
        "page_classifications": data.get("page_classifications", []),
        "ocr_boxes_failed_pages": data.get("ocr_boxes_failed_pages", []),
        "ocr_text_fallback_pages": data.get("ocr_text_fallback_pages", []),
        "ocr_text_fallback_unavailable_pages": data.get("ocr_text_fallback_unavailable_pages", []),
        "ocr_runtime_failed_pages": data.get("ocr_runtime_failed_pages", []),
        "ocr_correction": _slim_ocr_diagnostics(data.get("ocr_correction_diagnostics", {})),
        "split": data.get("split_diagnostics", {}),
        "risk_flag_counts": data.get("risk_flag_counts", {}),
        "batch_validation": data.get("batch_validation_diagnostics", {}),
        "schema_errors": data.get("errors", []),
        "ai_validation": data.get("ai_validation_diagnostics", {}),
        "similarity_match": data.get("similarity_match_diagnostics", {}),
        "stage_diffs": {
            "ocr_correction": _summarize_ocr_diffs(
                data.get("ocr_correction_diagnostics", {}).get("corrections", [])
            ),
            "code_language_noise": data.get("code_language_noise_fix_actions", []),
            "code_structure": data.get("fix_actions", []),
            "ai_repair": data.get("repair_diffs", []),
            "ai_repair_stats": data.get("repair_stats", {}),
        },
        # P3-4: review 分批提交 diagnostics
        "review_commit": data.get("review_commit"),
        # P3-7: shared token budget snapshot for monitoring
        "token_usage": _get_token_usage_snapshot_safe(),
        # ── 观察：split quality evaluation ──
        "split_quality": _slim_value(data.get("split_quality")),
        # ── 观察：per-run routing metrics ──
        "routing_metrics": _slim_value(data.get("routing_metrics")),
        # P6-2: per-stage performance profile
        "performance_profile": _build_performance_profile(
            {n: s.to_dict() for n, s in stages.items()},
            data,
        ) if stages else {},
        # ── Structure Freeze diagnostics ──
        "freeze_mode": data.get("freeze_mode", "legacy"),
        "freeze_dual_diagnostics": _slim_value(data.get("freeze_dual_diagnostics")),
        "freeze_ir_warnings": data.get("freeze_ir_warnings", []),
        # ── Domain Quality Gate shadow diagnostics ──
        "quality_gate_mode": _get_domain_quality_gate_mode(),
        "quality_gate_shadow_count": len(data.get("quality_gate_shadow_records", [])),
        "quality_gate_shadow_records": data.get("quality_gate_shadow_records", [])[:100],
    }
    return _slim_diagnostics_arrays(raw)


def _get_token_usage_snapshot_safe() -> dict:
    """Safe wrapper around token_budget.get_token_usage_snapshot()."""
    try:
        from app.features.token_budget import get_token_usage_snapshot
        return get_token_usage_snapshot()
    except Exception:
        return {"daily": 0, "monthly": 0}


def _get_ocr_cache_stats_safe() -> dict:
    """Safe wrapper around ocr_service.get_ocr_cache_stats()."""
    try:
        from app.services.ocr_service import get_ocr_cache_stats
        return get_ocr_cache_stats()
    except Exception:
        return {"hits": 0, "misses": 0, "hit_rate": 0.0}


# ---------------------------------------------------------------------------
# P6-2: update per-stage profiling metrics from pipeline data
# ---------------------------------------------------------------------------


def _update_stage_metrics(stage, data: dict, result: dict) -> None:
    """Set input/output counts and other per-stage profiling metrics.

    Derives counts from ``data`` (pre-stage state) and ``result`` (post-stage
    output) for each pipeline stage.  Called immediately after the stage runs.
    """
    name = stage.name
    # ── extract ──
    if name == "extract":
        stage.output_count = len(result.get("raw_blocks") or [])
    # ── normalize_text ──
    elif name == "normalize_text":
        stage.input_count = len(data.get("raw_blocks") or [])
        stage.output_count = len(result.get("normalized_blocks") or [])
    # ── ocr_correction ──
    elif name == "ocr_correction":
        stage.input_count = len(data.get("normalized_blocks") or [])
        stage.output_count = len(result.get("normalized_blocks") or [])
        # AI call count from correction diagnostics
        diag = result.get("ocr_correction_diagnostics") or {}
        corrections = diag.get("corrections") or []
        stage.ai_calls = diag.get("ai_calls", len(corrections))
        stage.tokens_used = diag.get("tokens_used", 0)
        # OCR cache stats
        cache_stats = _get_ocr_cache_stats_safe()
        stage.cache_hit = cache_stats.get("hits", 0)
        stage.cache_miss = cache_stats.get("misses", 0)
    # ── analyze_structure ──
    elif name == "analyze_structure":
        stage.input_count = len(data.get("normalized_blocks") or [])
        stage.output_count = 1  # single structure dict
    # ── classify_pages ──
    elif name == "classify_pages":
        stage.input_count = len(data.get("normalized_blocks") or [])
        stage.output_count = len(result.get("filtered_blocks") or
                                 result.get("page_classifications") or [])
    # ── split ──
    elif name == "split":
        stage.input_count = len(data.get("normalized_blocks") or [])
        stage.output_count = len(result.get("raw_questions") or [])
    # ── question_bbox ──
    elif name == "question_bbox":
        stage.input_count = len(data.get("raw_questions") or [])
        stage.output_count = len(result.get("raw_questions") or [])
    # ── match ──
    elif name == "match":
        stage.input_count = len(data.get("raw_questions") or [])
        stage.output_count = len(result.get("matched") or []) + len(result.get("unmatched") or [])
    # ── normalize_schema ──
    elif name == "normalize_schema":
        stage.input_count = len(data.get("questions") or [])
        stage.output_count = len(result.get("questions") or [])
    # ── code_language_noise_clean ──
    elif name == "code_language_noise_clean":
        stage.input_count = len(data.get("questions") or [])
        stage.output_count = len(result.get("questions") or [])
    # ── code_structure_reconstruct ──
    elif name == "code_structure_reconstruct":
        stage.input_count = len(data.get("questions") or [])
        stage.output_count = len(result.get("questions") or [])
        stage.ai_calls = result.get("reconstructed_count", 0)
    # ── batch_validation ──
    elif name == "batch_validation":
        stage.input_count = len(data.get("questions") or [])
        stage.output_count = 1  # validation result dict
    # ── batch_dedup ──
    elif name == "batch_dedup":
        stage.input_count = len(data.get("questions") or [])
        stage.output_count = len(result.get("questions") or [])
    # ── repair ──
    elif name == "repair":
        stage.input_count = len(data.get("questions") or [])
        stage.output_count = len(result.get("questions") or [])
        rstats = result.get("repair_stats") or {}
        stage.ai_calls = rstats.get("repaired_count", rstats.get("repaired", 0))
    # ── ai_validation ──
    elif name == "ai_validation":
        stage.input_count = len(data.get("questions") or [])
        stage.output_count = 1  # validation batch result
    # ── similarity_match ──
    elif name == "similarity_match":
        # pass-through stage, no meaningful counts
        pass
    # ── layout_reconstruction ──
    elif name == "layout_reconstruction":
        stage.input_count = len(data.get("normalized_blocks") or [])
        stage.output_count = 1  # single layout_result dict
    # ── layout_router ──
    elif name == "layout_router":
        stage.input_count = 1  # reads layout_result
        stage.output_count = 1  # produces split_mode
    # ── math_detect ──
    elif name == "math_detect":
        stage.input_count = len(data.get("questions") or [])
        stage.output_count = len(result.get("questions") or [])
    # ── table_detect ──
    elif name == "table_detect":
        stage.input_count = len(data.get("questions") or [])
        stage.output_count = len(result.get("questions") or [])
    # ── review ──
    elif name == "review":
        stage.input_count = len(data.get("questions") or [])
        stage.output_count = data.get("written", 0)


# ---------------------------------------------------------------------------
# P4-5: quality report after pipeline completion
# ---------------------------------------------------------------------------


def _build_quality_report(data: dict, diagnostics: dict) -> dict:
    """Build an import quality report from pipeline data and diagnostics.

    The report is derived from existing data — no extra queries.
    Returns a dict with optional fields (all fields can be absent/None
    without breaking the pipeline).
    """
    questions = data.get("questions") or []
    total = len(questions)

    # Risk distribution from per-question risk_flags
    low = 0
    medium = 0
    high = 0
    ai_answer_count = 0
    table_count = 0
    math_image_count = 0

    for q in questions:
        risk_flags = q.get("risk_flags") or []
        # Re-use the same classification as derive_import_risk
        is_high = bool(set(risk_flags) & {
            "answer_ai_generated", "code_uncertain", "formula_uncertain",
            "options_anomaly", "answer_missing", "ai_major_edit",
            "math_image_crop_failed", "table_low_confidence",
            "complex_formula_requires_review", "answer_missing",
        })
        if is_high:
            high += 1
        elif risk_flags:
            medium += 1
        else:
            low += 1

        if q.get("ai_answer_flag"):
            ai_answer_count += 1

        # Count segment types
        segments = q.get("segments") or (q.get("parsed_content") or {}).get("segments") or []
        for seg in segments:
            if seg.get("type") == "table_markdown":
                table_count += 1
            elif seg.get("type") == "math_image":
                math_image_count += 1

    # Repair stats
    repair_stats = data.get("repair_stats") or {}
    repair_skipped = repair_stats.get("skipped_count", repair_stats.get("skipped", 0))
    repair_called = repair_stats.get("repaired_count", repair_stats.get("repaired", 0))

    # Review idempotency
    review_commit = data.get("review_commit") or {}
    review_duplicates = review_commit.get("duplicates_filtered", 0)

    # OCR cache stats — read from global counters (process-lifetime,
    # first-pipeline report is most accurate; subsequent pipelines see
    # cumulative counts which are a reasonable upper bound).
    ocr_cache_stats = _get_ocr_cache_stats_safe()
    ocr_cache_hit = ocr_cache_stats.get("hits", 0)
    ocr_cache_miss = ocr_cache_stats.get("misses", 0)

    manual_review = medium + high
    estimated_rate = round(manual_review / total, 2) if total > 0 else 0

    report: dict = {
        "total_questions": total,
    }
    if low > 0:
        report["low_risk"] = low
    if medium > 0:
        report["medium_risk"] = medium
    if high > 0:
        report["high_risk"] = high
    if manual_review > 0:
        report["requires_manual_review"] = manual_review
    if ai_answer_count > 0:
        report["ai_answer_count"] = ai_answer_count
    if math_image_count > 0:
        report["math_image_count"] = math_image_count
    if table_count > 0:
        report["table_markdown_count"] = table_count
    if repair_skipped > 0:
        report["repair_skipped"] = repair_skipped
    if repair_called > 0:
        report["repair_called"] = repair_called
    if ocr_cache_hit > 0:
        report["ocr_cache_hit"] = ocr_cache_hit
    if ocr_cache_miss > 0:
        report["ocr_cache_miss"] = ocr_cache_miss
    if review_duplicates > 0:
        report["review_duplicates_skipped"] = review_duplicates
    if total > 0:
        report["estimated_manual_check_rate"] = estimated_rate

    return report


# ---------------------------------------------------------------------------
# P6-2: performance profile from per-stage metrics
# ---------------------------------------------------------------------------


def _build_performance_profile(stages: dict[str, Any], data: dict) -> dict:
    """Build performance profile from per-stage metrics.

    Each stage reports: duration_ms, input_count, output_count,
    cache_hit/miss, ai_calls, tokens_used.
    Aggregated into a performance_profile dict.
    """
    profile: dict[str, dict] = {}
    for name, s in stages.items():
        entry: dict[str, Any] = {"duration_ms": s.get("duration_ms", 0)}
        if s.get("input_count"):
            entry["input_count"] = s["input_count"]
        if s.get("output_count"):
            entry["output_count"] = s["output_count"]
        if s.get("cache_hit"):
            entry["cache_hit"] = s["cache_hit"]
        if s.get("cache_miss"):
            entry["cache_miss"] = s["cache_miss"]
        if s.get("ai_calls"):
            entry["ai_calls"] = s["ai_calls"]
        if s.get("tokens_used"):
            entry["tokens_used"] = s["tokens_used"]
        profile[name] = entry

    # Compute totals
    total_duration = sum(e["duration_ms"] for e in profile.values())
    total_ai_calls = sum(e.get("ai_calls", 0) for e in profile.values())
    total_tokens = sum(e.get("tokens_used", 0) for e in profile.values())
    cache_hits = sum(e.get("cache_hit", 0) for e in profile.values())
    cache_misses = sum(e.get("cache_miss", 0) for e in profile.values())

    # Find slowest stage
    if profile:
        slowest = max(profile.items(), key=lambda kv: kv[1]["duration_ms"])
        profile["_summary"] = {
            "total_duration_ms": total_duration,
            "total_ai_calls": total_ai_calls,
            "total_tokens_used": total_tokens,
            "total_cache_hits": cache_hits,
            "total_cache_misses": cache_misses,
            "cache_hit_rate": round(cache_hits / (cache_hits + cache_misses), 2) if (cache_hits + cache_misses) > 0 else 0,
            "slowest_stage": slowest[0],
            "slowest_duration_ms": slowest[1]["duration_ms"],
        }

    return profile


def _log_routing_stability(
    pipeline_id: str, routing_metrics: dict, split_quality: dict | None
) -> None:
    """Log routing stability record for production monitoring.

    格式固化，可用于后续监控系统稳定性分析。
    """
    logger.info(
        "routing_stability pipeline_id=%s layout_confidence=%.3f route=%s "
        "final_split_quality_score=%.3f vl_triggered=%s",
        pipeline_id,
        routing_metrics.get("layout_confidence", 0.0),
        routing_metrics.get("split_mode", "unknown"),
        (split_quality or {}).get("split_quality_score", 0.0),
        routing_metrics.get("split_mode") == "vl_rebuild",
    )


def _slim_diagnostics_arrays(diagnostics: dict) -> dict:
    """P0-3: 截断 diagnostics 中的大数组，限制每条诊断记录的内存占用。

    对于 400 页 PDF 的单 pass 路径，page_classifications、exercise_regions
    等数组可达数百条。本函数为所有数组类字段统一设上限，超出的部分截断并注
    记 truncated 计数。
    """
    if not diagnostics:
        return diagnostics

    array_caps = {
        "page_classifications": 50,
        "exercise_regions": 100,
        "ocr_boxes_failed_pages": 50,
        "ocr_text_fallback_pages": 50,
        "ocr_text_fallback_unavailable_pages": 50,
        "ocr_runtime_failed_pages": 50,
    }

    for key, cap in array_caps.items():
        arr = diagnostics.get(key)
        if isinstance(arr, list) and len(arr) > cap:
            diagnostics = {
                **diagnostics,
                key: arr[:cap],
                f"{key}_truncated": len(arr) - cap,
            }

    # structure 内的列表字段也截断
    structure = diagnostics.get("structure")
    if isinstance(structure, dict):
        slim_structure: dict[str, Any] = {}
        for skey in ("question_pages", "answer_pages", "explanation_pages",
                       "content_pages", "section_markers"):
            val = structure.get(skey)
            if isinstance(val, list) and len(val) > 50:
                slim_structure[skey] = val[:50]
                slim_structure[f"{skey}_truncated"] = len(val) - 50
            elif val is not None:
                slim_structure[skey] = val
        # 保留其他非列表字段
        for skey, sval in structure.items():
            if skey not in slim_structure:
                slim_structure[skey] = sval
        diagnostics = {**diagnostics, "structure": slim_structure}

    # split 内的 layout_filter.region_signals 截断
    split = diagnostics.get("split")
    if isinstance(split, dict):
        lf = split.get("layout_filter")
        if isinstance(lf, dict):
            signals = lf.get("region_signals")
            if isinstance(signals, list) and len(signals) > 50:
                split = {
                    **split,
                    "layout_filter": {
                        **lf,
                        "region_signals": signals[:50],
                        "region_signals_truncated": len(signals) - 50,
                    },
                }
                diagnostics = {**diagnostics, "split": split}

    return diagnostics


def _slim_chunk_diagnostics(diagnostics: dict) -> dict:
    split = diagnostics.get("split") or {}
    slim_split: dict[str, Any] = {}
    for key in ("layout_filter", "visual_boundary", "failure_reason"):
        if key in split:
            slim_split[key] = split[key]
    return {
        "split": slim_split,
        "risk_flag_counts": diagnostics.get("risk_flag_counts") or {},
    }


def _merge_risk_flag_counts(chunks: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in chunks:
        chunk_counts = (chunk.get("diagnostics") or {}).get("risk_flag_counts") or {}
        for flag, count in chunk_counts.items():
            counts[str(flag)] = counts.get(str(flag), 0) + int(count or 0)
    return counts


def _visual_boundary_preview(blocks: list[dict], boundary: dict) -> str:
    """Return a safe summary for boundary preview (never raw text)."""
    import hashlib
    block_index = boundary.get("block_index")
    line_index = boundary.get("line_index")
    if not isinstance(block_index, int) or not isinstance(line_index, int):
        return ""
    for block in blocks:
        if block.get("block_index", 0) != block_index:
            continue
        text = block.get("normalized_text") or block.get("text") or ""
        lines = str(text).split("\n")
        if 0 <= line_index < len(lines):
            joined = "".join(line.strip() for line in lines[line_index:line_index + 2])
            return hashlib.md5(joined.encode()).hexdigest()[:12]
    return ""


# ---------------------------------------------------------------------------
# PipelineStage
# ---------------------------------------------------------------------------


class PipelineStage:
    """单个阶段的执行单元，记录状态、耗时和警告。"""

    def __init__(self, name: str, fn):
        self.name = name
        self.fn = fn
        self.status = "pending"  # pending → running → completed | failed
        self.duration_ms = 0
        self.warnings: list[str] = []
        self.error: str | None = None
        # P6-2: per-stage performance profiling
        self.input_count = 0
        self.output_count = 0
        self.cache_hit = 0
        self.cache_miss = 0
        self.ai_calls = 0
        self.tokens_used = 0
        self.memory_mb_peak = 0

    def run(self, **kwargs):
        """同步执行阶段（阻塞）。"""
        self.status = "running"
        start = time.monotonic()
        try:
            result = self.fn(**kwargs)
            self.status = "completed"
            self.duration_ms = round((time.monotonic() - start) * 1000)
            return result
        except Exception as exc:
            self.status = "failed"
            self.error = str(exc)
            self.duration_ms = round((time.monotonic() - start) * 1000)
            raise

    async def run_async(self, **kwargs):
        """异步执行阶段。"""
        self.status = "running"
        start = time.monotonic()

        _pipe_logger = logging.getLogger("app.pipeline")

        # Stage -> business domain mapping (for Sentry trace linking)
        from app.features.pipeline_definition import PipelineDefinition as _PipeDef
        _STAGE_BUSINESS_MAP = _PipeDef.business_map()
        set_tag("stage", _STAGE_BUSINESS_MAP.get(self.name, "unknown"))
        set_tag("pipeline.stage", self.name)
        bind_log_context(stage=self.name)

        log_event(
            _pipe_logger, "pipeline.stage.start",
            stage=self.name,
        )

        with start_span(op=f"pipeline.{self.name}", description=f"stage={self.name}"):
            try:
                if asyncio.iscoroutinefunction(self.fn):
                    result = await self.fn(**kwargs)
                else:
                    result = await asyncio.to_thread(self.fn, **kwargs)
                self.status = "completed"
                self.duration_ms = round((time.monotonic() - start) * 1000)
                set_tag("pipeline.stage_status", "completed")
                set_tag("pipeline.stage_duration_ms", self.duration_ms)

                log_event(
                    _pipe_logger, "pipeline.stage.finish",
                    stage=self.name,
                    duration_ms=self.duration_ms,
                    status="completed",
                    input_count=self.input_count,
                    output_count=self.output_count,
                    cache_hit=self.cache_hit,
                    cache_miss=self.cache_miss,
                    ai_calls=self.ai_calls,
                    tokens_used=self.tokens_used,
                )
                return result
            except Exception as exc:
                self.status = "failed"
                self.error = str(exc)
                self.duration_ms = round((time.monotonic() - start) * 1000)
                set_tag("pipeline.stage_status", "failed")
                capture_exception(
                    exc,
                    tags={"pipeline.stage": self.name, "stage": _STAGE_BUSINESS_MAP.get(self.name, "unknown")},
                )

                logger.exception("Pipeline stage '%s' failed: %s", self.name, exc)

                log_event(
                    _pipe_logger, "pipeline.stage.error",
                    level="error",
                    stage=self.name,
                    duration_ms=self.duration_ms,
                    status="failed",
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:300],
                )
                raise

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "warnings": self.warnings,
        }
        if self.error:
            d["error"] = self.error
        # P6-2: include non-zero profiling fields only to keep payload small
        if self.input_count:
            d["input_count"] = self.input_count
        if self.output_count:
            d["output_count"] = self.output_count
        if self.cache_hit:
            d["cache_hit"] = self.cache_hit
        if self.cache_miss:
            d["cache_miss"] = self.cache_miss
        if self.ai_calls:
            d["ai_calls"] = self.ai_calls
        if self.tokens_used:
            d["tokens_used"] = self.tokens_used
        if self.memory_mb_peak:
            d["memory_mb_peak"] = self.memory_mb_peak
        return d


# ---------------------------------------------------------------------------
# ImportPipeline
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# P4-3: artifact-based true resume helpers
# ---------------------------------------------------------------------------


def _save_stage_artifact(pipeline_id: str, stage_name: str, data: dict) -> None:
    """Save the current stage output as an artifact for later resume.

    Only resumable stages are saved.  The artifact is a JSON file on disk
    under ``.backend_cache/pipeline_artifacts/{pipeline_id}/``.
    """
    if stage_name == "split":
        _save_artifact(pipeline_id, "split", {
            "raw_questions": data.get("raw_questions", []),
            "structure": data.get("structure"),
            "source_file": data.get("source_file", ""),
            "source_type": data.get("source_type", ""),
            "subject": data.get("subject"),
        })
    elif stage_name == "normalize_schema":
        _save_artifact(pipeline_id, "normalize_schema", {
            "questions": data.get("questions", []),
            "source_file": data.get("source_file", ""),
            "source_type": data.get("source_type", ""),
            "subject": data.get("subject"),
        })
    elif stage_name == "repair":
        _save_artifact(pipeline_id, "repair", {
            "questions": data.get("questions", []),
        })
    elif stage_name == "math_detect":
        _save_artifact(pipeline_id, "math_detect", {
            "questions": data.get("questions", []),
        })
    elif stage_name == "table_detect":
        _save_artifact(pipeline_id, "table_detect", {
            "questions": data.get("questions", []),
        })
    elif stage_name == "review":
        _save_artifact(pipeline_id, "review", {
            "batch_id": data.get("batch_id", ""),
            "written": data.get("written", 0),
        })


def _restore_from_artifacts(
    pipeline_id: str,
    completed_stages: list[str],
    data: dict,
) -> tuple[str | None, set[str]]:
    """Try to restore stage outputs from saved artifacts.

    P0-1: Uses canonical stage ordering from pipeline_artifacts.stages_before()
    to compute which stages can be skipped.  No more hardcoded ``preceding``
    sets that drift from the actual pipeline.

    Returns:
        (restored_stage, skipped_stages_set) where restored_stage is the
        resume point and skipped_stages_set contains the stage names that
        can be skipped.  Both are empty if nothing was restored (full re-run).
    """
    from app.features.pipeline_artifacts import (
        artifact_exists as _artifact_exists,
        check_artifact_compatibility,
        stages_before,
    )

    # Priority order: most advanced first
    resume_artifacts = [
        "table_detect",
        "math_detect",
        "repair",
        "normalize_schema",
        "split",
    ]

    for stage_name in resume_artifacts:
        if not _artifact_exists(pipeline_id, stage_name):
            continue
        # Check compatibility (reject version mismatches)
        compatible, reason = check_artifact_compatibility(pipeline_id, stage_name)
        if not compatible:
            logger.warning(
                "Cannot resume from %s artifact: %s",
                stage_name, reason,
            )
            continue

        saved = _load_artifact(pipeline_id, stage_name)
        if saved is None:
            continue

        if stage_name == "split":
            raw_questions = saved.get("raw_questions", [])
            if not raw_questions:
                continue
            data["raw_questions"] = raw_questions
            data["split_count"] = len(raw_questions)
            data["structure"] = saved.get("structure")
            data["source_file"] = saved.get("source_file", data.get("source_file", ""))
            data["source_type"] = saved.get("source_type", data.get("source_type", ""))
            data["subject"] = saved.get("subject", data.get("subject"))
            # Derive preceding stages from canonical order (dynamic, no hardcoded sets)
            preceding_set = set(stages_before(stage_name))
            for s in preceding_set - {"split"}:
                if s not in completed_stages:
                    completed_stages.append(s)
            logger.info(
                "Resume from split artifact: %d raw_questions restored",
                len(raw_questions),
            )
            return stage_name, preceding_set

        elif stage_name in ("normalize_schema", "repair", "math_detect", "table_detect"):
            questions = saved.get("questions", [])
            if not questions:
                continue
            data["questions"] = questions
            data["normalized_count"] = len(questions)
            # Derive preceding stages from canonical order — stages_before gives
            # ALL stages at or before the artifact stage. We also need to include
            # stages like "match" that come before "normalize_schema".
            # The key insight: stages_before(stage) returns all stages that are
            # strictly before stage. We want to include the stage itself too
            # (since its output IS the artifact), so we add it.
            preceding_set = set(stages_before(stage_name))
            preceding_set.add(stage_name)
            for s in preceding_set:
                if s not in completed_stages:
                    completed_stages.append(s)
            logger.info(
                "Resume from %s artifact: %d questions restored (derived %d preceding stages)",
                stage_name, len(questions), len(preceding_set),
            )
            return stage_name, preceding_set

    return None, set()


# ---------------------------------------------------------------------------
# ImportPipeline
# ---------------------------------------------------------------------------


class ImportPipeline:
    """导入流水线，编排 Stage 1-7。

    使用方式::

        pipeline = ImportPipeline(options={"enable_ai_repair": True})
        result = await pipeline.run(
            file_content=pdf_bytes,
            source_type="pdf",
            source_file="exam.pdf",
            subject="math2",
            db=db_session,
        )
    """

    def __init__(self, options: dict | None = None):
        self.options = options or {}
        self.pipeline_id = ""
        self.stages: dict[str, PipelineStage] = {}
        # P0-1 / P0-2: 透传到 ckpt.create_pipeline_record，落到
        # import_pipelines.created_by / source_sha256，让 resume endpoint 能
        # 校验创建者身份与原始 PDF 字节摘要。仅 chunked PDF 路径设值，单 pass
        # 路径不创建 pipeline 行因此无需透传。
        self.created_by: str | None = None
        self.source_sha256: str | None = None

    def _build_pipeline(self) -> None:
        """(Re)build the stage list from current options.

        Called during __init__ and whenever options change at runtime.
        Iterates ``PipelineDefinition.enabled_stages()`` so the stage order,
        conditional enable, and runner binding live in one place.
        """
        from app.features.pipeline_definition import PipelineDefinition as _PipeDef

        stage_specs: list[tuple[str, callable]] = []
        for sd in _PipeDef.enabled_stages(self.options):
            fn = getattr(self, sd.runner_method, None)
            if fn is None:
                raise ValueError(
                    f"No runner method {sd.runner_method!r} for stage {sd.name!r}"
                )
            stage_specs.append((sd.name, fn))

        self.stages.clear()
        for name, fn in stage_specs:
            self.stages[name] = PipelineStage(name, fn)

    def _run_extract(
        self,
        file_content: bytes | None = None,
        source_type: str = "pdf",
        file_path: str | None = None,
        **_kw,
    ) -> dict:
        """Extract raw text blocks from file content.

        For PDFs with very little extractable text (< 100 chars), triggers OCR
        fallback automatically when OCR_ENABLED is True.

        Single OCR pass: _ocr_scanned_pdf runs once at full quality. Exercise
        detection (when enabled) reuses the same OCR text — no separate
        lightweight scan (Task 2: 消除双 OCR).

        file_path 优先仅适用于 PDF（fitz mmap 优化）。
        image / txt 优先使用 file_content（OCR 后的 cleaned_text），
        避免把 PNG/JPEG 图片文件当文本 decode。
        """
        if source_type == "pdf":
            # 路径优先：底层 fitz.open 走 mmap，避免把 100~400 MB 拷到 heap
            pdf_source: bytes | str = file_path if file_path else file_content
            if pdf_source is None:
                raise ValueError("either file_path or file_content must be provided")

        if source_type == "pdf":
            opts = _kw.get("options") or {}
            raw_blocks = _extract_pdf_blocks(
                pdf_source,
                page_start=opts.get("page_start") or 1,
                page_end=opts.get("page_end"),
            )

            exercise_regions_result: list[dict] = []
            # P1-2: 仅当 exercise_regions 检测真正跑了但返回为空时设为 True；
            # 用户指定 page_start/page_end、exam 模式、OCR 未启用等场景下保持
            # False，避免误打 no_exercise_regions 风险标。
            exercise_regions_missing = False

            # Scanned PDF detection: if PyMuPDF extracted very little text,
            # the PDF likely contains only images → trigger OCR fallback.
            #
            # Single OCR pass: _ocr_scanned_pdf at normal DPI with full
            # PaddleOCR box-level output. Exercise detection reuses the
            # same OCR text — no separate lightweight pass (Task 2).
            total_text = sum(len(b.get("text", "")) for b in raw_blocks)
            if total_text < 100:
                from app.core.config import settings

                if settings.OCR_ENABLED:
                    logger.info(
                        "PDF text only %d chars, attempting PaddleOCR fallback", total_text,
                    )
                    ocr_ok = False
                    try:
                        import_mode_str = opts.get("import_mode", "auto")
                        user_specified_range = opts.get("page_start") or opts.get("page_end")

                        # ── Single OCR pass (the ONLY PaddleOCR call) ──
                        ocr_page_start = opts.get("page_start") or 1
                        ocr_page_end = opts.get("page_end")
                        ocr_blocks = _ocr_scanned_pdf(
                            pdf_source,
                            pipeline_id=self.pipeline_id,
                            page_start=ocr_page_start,
                            page_end=ocr_page_end,
                        )

                        if ocr_blocks:
                            raw_blocks = ocr_blocks
                            ocr_ok = True

                            # Exercise detection reuses the full OCR text —
                            # no separate lightweight OCR pass (Task 2)
                            if (settings.EXERCISE_DETECTION_ENABLED
                                    and import_mode_str != "exam"
                                    and not user_specified_range):
                                from app.features.exercise_region_detector import (
                                    detect_exercise_regions,
                                )

                                page_texts = _extract_page_texts_from_blocks(raw_blocks)
                                exercise_regions = detect_exercise_regions(
                                    page_texts,
                                    config={
                                        "max_empty_pages": settings.EXERCISE_DETECTION_MAX_EMPTY_PAGES,
                                        "min_confidence": settings.EXERCISE_DETECTION_MIN_CONFIDENCE,
                                    },
                                )

                                if exercise_regions:
                                    exercise_regions_result = [
                                        {"start_page": r.start_page, "end_page": r.end_page,
                                         "confidence": r.confidence, "matched_keyword": r.matched_keyword}
                                        for r in exercise_regions
                                    ]
                                    # Filter blocks to exercise region pages
                                    region_pages: set[int] = set()
                                    for r in exercise_regions:
                                        for p in range(r.start_page, r.end_page + 1):
                                            region_pages.add(p)
                                    raw_blocks = [b for b in raw_blocks if b.get("page", 0) in region_pages]
                                    logger.info(
                                        "Exercise region detection found %d region(s), filtered to %d blocks",
                                        len(exercise_regions), len(raw_blocks),
                                    )
                                    del exercise_regions
                                else:
                                    exercise_regions_missing = True
                                    logger.info(
                                        "Exercise detection found no regions, keeping all %d OCR blocks",
                                        len(raw_blocks),
                                    )
                            elif user_specified_range:
                                logger.info(
                                    "Skipping exercise detection: user specified page range %s-%s",
                                    opts.get("page_start"), opts.get("page_end"),
                                )

                            logger.info("OCR succeeded: %d blocks", len(raw_blocks))
                        else:
                            logger.warning("OCR returned no blocks")
                    except RuntimeError as exc:
                        logger.warning("OCR fallback unavailable: %s", exc)
                    except Exception as exc:
                        logger.warning(
                            "OCR fallback failed, using original extraction: %s", exc,
                        )

                    # PaddleOCR-VL 不在此处调用 — 由下游 ocr_correction 阶段的路由器统一处理
                    if not ocr_ok:
                        logger.warning(
                            "Local OCR returned no blocks; downstream ocr_correction stage "
                            "will attempt PaddleOCR-VL via OCRFixRouter"
                        )
                else:
                    logger.warning(
                        "PDF text only %d chars but OCR_ENABLED=false, cannot extract scanned content",
                        total_text,
                    )

            if not raw_blocks:
                raise ValueError(
                    "PDF 中未提取到文本内容（文本层为空且 OCR 未启用或失败）"
                )
        else:
            text_source = file_content if file_content is not None else file_path
            if text_source is None:
                raise ValueError("either file_content or file_path must be provided")
            raw_blocks = _extract_text_blocks(text_source)
            exercise_regions_result = []
            exercise_regions_missing = False

        return {
            "raw_blocks": raw_blocks,
            "extracted": len(raw_blocks),
            "_original_raw_text": (_kw.get("options") or {}).get("_original_raw_text", ""),
            "exercise_regions": exercise_regions_result,
            "exercise_regions_missing": exercise_regions_missing,
            "ocr_boxes_failed_pages": sorted({
                int(b.get("page") or b.get("page_index") or 0)
                for b in raw_blocks
                if b.get("_ocr_boxes_failed") and (b.get("page") or b.get("page_index"))
            }),
            "ocr_text_fallback_pages": sorted({
                int(b.get("page") or b.get("page_index") or 0)
                for b in raw_blocks
                if b.get("source") == "ocr_text_fallback" and (b.get("page") or b.get("page_index"))
            }),
            "ocr_text_fallback_unavailable_pages": sorted({
                int(page)
                for b in raw_blocks
                for page in (b.get("_ocr_text_fallback_unavailable_pages") or [])
                if page
            }),
            "ocr_runtime_failed_pages": sorted({
                int(page)
                for b in raw_blocks
                for page in (b.get("_ocr_runtime_failed_pages") or [])
                if page
            }),
        }

    def _run_wangdao_preprocess(self, raw_blocks: list[dict], **_kw) -> dict:
        """Pre-processing stage for Wangdao PDF: filter watermarks/headers/footers."""
        from app.features.wangdao_preprocessor import preprocess_wangdao_blocks

        filtered = preprocess_wangdao_blocks(raw_blocks)

        removed = len(raw_blocks) - len(filtered)
        warnings: list[str] = []
        if removed:
            warnings.append(f"wangdao_preprocess: removed {removed} blocks (watermark/header/footer)")

        return {"raw_blocks": filtered, "warnings": warnings}

    async def _run_normalize_text(self, raw_blocks: list[dict], **_kw) -> dict:
        """Stage 1: text cleaning via ImportTextNormalizer."""
        extra_patterns = _kw.get("watermark_patterns") or []

        # 从 DB admin_ai_configs 加载 ocr_strategy_* 开关
        db = _kw.get("db")
        enabled_strategies = await self._load_ocr_strategies(db)

        normalizer = ImportTextNormalizer(
            extra_watermark_patterns=extra_patterns,
            enabled_strategies=enabled_strategies,
        )
        normalized_blocks = normalizer.normalize(raw_blocks)

        for b in normalized_blocks:
            raw = b.get("text") or ""
            norm = b.get("normalized_text") or ""
            if raw and norm and raw != norm:
                logger.info(
                    "【OCR-3】text_normalizer 修正 | block=%d page=%s len=%d→%d\n"
                    "  └─ 原始: %.160s\n  └─ 清洗: %.160s",
                    b.get("block_index", 0), b.get("page", "?"),
                    len(raw), len(norm), raw, norm,
                )

        warnings: list[str] = []
        empty_count = sum(1 for b in normalized_blocks if not b.get("normalized_text"))
        if empty_count:
            warnings.append(f"{empty_count} blocks empty after normalization")

        return {"normalized_blocks": normalized_blocks, "warnings": warnings}

    def _run_layout_reconstruction(
        self,
        normalized_blocks: list[dict],
        **_kw,
    ) -> dict:
        """Stage 1.7: spatial layout reconstruction before structure analysis.

        Uses OCR bbox + geometry heuristics to:
        - Detect columns (single/double-column pages)
        - Cluster option blocks (A./B./C./D. patterns)
        - Reconstruct reading order
        - Compute layout confidence score

        Pure rule-based — no LLM dependency.
        """
        from app.features.pipeline_stages.layout_stage import (
            run_layout_reconstruction_stage_from_ir,
        )

        doc_ir = _get_blocks_document_ir(normalized_blocks)
        if doc_ir is not None:
            result = run_layout_reconstruction_stage_from_ir(doc_ir)
        else:
            result = run_layout_reconstruction_stage(normalized_blocks=normalized_blocks)

        warnings: list[str] = list(result.get("warnings", []))
        layout_result = result.get("layout_result", {})

        # Enrich normalized_blocks with layout_info (done in-place by reconstruct_layout)
        enriched_blocks = result.get("layout_blocks", normalized_blocks)
        layout_confidence = result.get("layout_confidence", 1.0)

        page_layouts: dict = layout_result.get("page_layouts", {})
        multi_col_count = sum(
            1 for pl in page_layouts.values()
            if getattr(pl, "is_multicolumn", False)
        ) if isinstance(page_layouts, dict) else 0

        logger.info(
            "Layout reconstruction: confidence=%.2f, "
            "multicolumn=%d pages, option_groups=%d pages, "
            "warnings=%d",
            layout_confidence,
            multi_col_count,
            len(layout_result.get("option_groups", {})),
            len(warnings),
        )

        return {
            "normalized_blocks": enriched_blocks,
            "layout_result": layout_result,
            "warnings": warnings,
        }

    def _run_layout_router(self, layout_result: dict, strategy: dict | None = None, options: dict | None = None, **_kw) -> dict:
        """Stage 1.8: 结构感知路由决策。

        根据 layout_reconstruction 的质量评估结果，决定下游 split 模式：
            standard        — 结构清晰，标准 split + layout 注入
            layout_enhanced — 结构不稳定，layout+OCR 融合 split
            vl_rebuild      — 结构失败，触发 PaddleOCR-VL 重建

        纯规则决定，不依赖 LLM。
        routing 只由本方法决定，下游不重复评估。

        strategy / options 中的 force_split_mode 可覆盖路由决策（仅用于 A/B 实验基线）。
        """
        from app.features.layout_router import evaluate_routing

        # Allow override for A/B experiment baseline
        force_mode = (
            (strategy or {}).get("force_split_mode")
            or (options or {}).get("strategy", {}).get("force_split_mode")
        )
        if force_mode:
            split_mode = force_mode
            logger.info(
                "Layout router: FORCED mode=%s (strategy override, "
                "original confidence=%.2f, opt_score=%.2f)",
                split_mode,
                layout_result.get("layout_confidence", 1.0),
                layout_result.get("option_detection_score", 1.0),
            )
        else:
            split_mode = evaluate_routing(layout_result)

        logger.info(
            "Layout router: mode=%s (confidence=%.2f, "
            "opt_score=%.2f, opt_failed=%s)",
            split_mode,
            layout_result.get("layout_confidence", 1.0),
            layout_result.get("option_detection_score", 1.0),
            layout_result.get("option_detection_failed", False),
        )

        return {"split_mode": split_mode}

    def _run_vl_rebuild_blocks(
        self,
        file_path: str,
        original_blocks: list[dict],
        vl_config: dict | None = None,
        original_raw_text: str = "",
    ) -> list[dict] | None:
        """用 PaddleOCR-VL 重建 blocks（VL_REBUILD 路径）。

        当 layout 结构失败时，通过 OCRFixRouter 调用 PaddleOCR-VL 从原始
        页面（PDF 或图片）重新识别文字，输出与 normalized_blocks 兼容的格式。

        Args:
            file_path: PDF 或图片文件路径。
            original_blocks: 当前 normalized_blocks（用于获取 page_width/page_height）。
            vl_config: PaddleOCR-VL 配置（含 api_key, api_base_url, model_name）。

        Returns:
            list[dict] 重建后的 blocks，或 None（不可用/失败）。
        """
        if not vl_config:
            logger.warning("VL_REBUILD: no vision config available")
            return None

        file_lower = file_path.lower()
        is_pdf = file_lower.endswith(".pdf")
        is_image = any(file_lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg"))

        if not is_pdf and not is_image:
            logger.warning("VL_REBUILD: unsupported file type: %s", file_path)
            return None

        try:
            api_token = vl_config.get("api_key") or vl_config.get("paddleocr_vl_api_token") or ""
            base_url = vl_config.get("api_base_url") or "https://paddleocr.aistudio-app.com"
            model = vl_config.get("model_name") or "PaddleOCR-VL-1.6"

            if not api_token:
                logger.warning("VL_REBUILD: PaddleOCR-VL not configured")
                return None

            # 通过 OCRFixRouter 调用 PaddleOCR-VL（唯一入口）
            from app.features.ocr_fix.router import OCRFixRouter, STRATEGY_MANUAL

            router = OCRFixRouter()
            router.configure({
                "ocr_fix_strategy": STRATEGY_MANUAL,
                "ocr_fix_model": "paddleocr-vl",
                "paddleocr_vl_api_token": api_token,
                "paddleocr_vl_base_url": base_url,
                "paddleocr_vl_model": model,
            })

            new_blocks: list[dict] = []
            page_batches: list[tuple[int, bytes, int, int]] = []  # (page_idx, png_bytes, pw, ph)

            if is_pdf:
                # ── PDF path: render each page to image ──
                import fitz
                doc = fitz.open(file_path, filetype="pdf")
                try:
                    total_pages = len(doc)

                    page_dim: dict[int, tuple[int, int]] = {}
                    for b in original_blocks:
                        p = b.get("page") or b.get("page_index") or 0
                        pw = b.get("page_width") or 800
                        ph = b.get("page_height") or 1200
                        if p not in page_dim:
                            page_dim[p] = (pw, ph)

                    for page_num in range(total_pages):
                        page_idx = page_num + 1
                        pix = doc[page_num].get_pixmap(dpi=150)
                        png_bytes = pix.tobytes("png")
                        pw, ph = page_dim.get(page_idx, (pix.width, pix.height))
                        page_batches.append((page_idx, png_bytes, pw, ph))
                finally:
                    doc.close()
            else:
                # ── Image path: read file directly ──
                import os
                if not os.path.isfile(file_path):
                    logger.warning("VL_REBUILD: image file not found: %s", file_path)
                    return None

                with open(file_path, "rb") as f:
                    image_bytes = f.read()

                pw, ph = 800, 1200
                if original_blocks:
                    b0 = original_blocks[0]
                    pw = b0.get("page_width") or pw
                    ph = b0.get("page_height") or ph
                page_batches.append((1, image_bytes, pw, ph))

            # ── Dual-source strategy: PP-OCRv4 primary, VL fallback ──
            from app.features.ocr_correction_common import repair_option_structure
            from app.features.question_type_classifier import (
                detect_options_from_text, extract_options_from_text,
            )

            for page_idx, png_bytes, pw, ph in page_batches:
                best_text = ""
                pp_opt_count = 0

                # Phase 1: Run PP-OCRv6 locally (structure primary)
                try:
                    from app.services.ocr_service import ocr_raw_text

                    pp_text = ocr_raw_text(png_bytes)

                    if detect_options_from_text(pp_text):
                        best_text = pp_text
                        pp_opt_count = len(extract_options_from_text(pp_text))
                        logger.info(
                            "VL_REBUILD page %d: PP-OCRv4 (%d chars, %d options detected)",
                            page_idx, len(pp_text), pp_opt_count,
                        )
                except Exception as exc:
                    logger.warning("VL_REBUILD PP-OCRv4 failed page %d: %s", page_idx, exc)

                # Phase 2: Call VL when PP-OCR has fewer than 4 options
                # (PP-OCR re-run on raw image can miss options that VL recovers)
                if pp_opt_count < 4:
                    ctx = {"page_num": page_idx, "filename": f"page_{page_idx}.png", "entry_point": "vl_rebuild"}
                    result = _run_coro_in_loop(
                        router.fix(image=png_bytes, ocr_text="", context=ctx)
                    )

                    if result and result.fixed_text:
                        vl_raw = result.fixed_text.strip()
                        repaired = repair_option_structure(vl_raw)
                        vl_has_opts = detect_options_from_text(repaired)
                        vl_text = repaired if vl_has_opts else vl_raw
                        vl_opt_count = len(extract_options_from_text(vl_text)) if vl_has_opts else 0

                        if vl_opt_count > pp_opt_count:
                            best_text = vl_text
                            logger.info(
                                "VL_REBUILD page %d: switching to VL (%d chars, %d options "
                                "vs PP-OCR's %d)",
                                page_idx, len(best_text), vl_opt_count, pp_opt_count,
                            )
                        elif not best_text:
                            best_text = vl_text
                            logger.info(
                                "VL_REBUILD page %d: using VL (%d chars, options=%s)",
                                page_idx, len(best_text), vl_has_opts,
                            )

                # Phase 3: Check original_raw_text for missing options.
                # PP-OCR re-run and VL may each miss different options (e.g.
                # re-run has A correct but B garbled, original has B correct
                # but A garbled). Extract from original and merge.
                if best_text and original_raw_text:
                    current_opts = extract_options_from_text(best_text)
                    original_opts = extract_options_from_text(original_raw_text)
                    if original_opts:
                        missing = set(original_opts.keys()) - set(current_opts.keys())
                        if missing:
                            for line in original_raw_text.split("\n"):
                                for key in list(missing):
                                    prefix = f"{key}."
                                    if line.strip().startswith(prefix):
                                        best_text = best_text + "\n" + line
                                        current_opts[key] = original_opts[key]
                                        missing.remove(key)
                                        logger.info(
                                            "VL_REBUILD page %d: merged option %s from "
                                            "original_raw_text (now %d options)",
                                            page_idx, key, len(current_opts),
                                        )
                                        break

                if best_text:
                    # Clean standalone page/order markers (<1>, <2>, <>, etc.)
                    # that OCR introduces as transition noise
                    best_text = re.sub(
                        r"(?:^|\n)\s*<\d*>\s*(?:\n|$)", r"\n", best_text
                    ).strip()
                    new_blocks.append({
                        "page": page_idx,
                        "page_index": page_idx,
                        "block_index": len(new_blocks),
                        "text": best_text,
                        "normalized_text": best_text,
                        "boxes": [],
                        "page_width": pw,
                        "page_height": ph,
                        "source": "vl_rebuild",
                        "has_boxes": False,
                    })

            if not new_blocks:
                logger.warning("VL_REBUILD: no blocks produced")
                return None

            logger.info(
                "VL_REBUILD: %d blocks from %s",
                len(new_blocks), "PDF" if is_pdf else "image",
            )
            return new_blocks

        except Exception as exc:
            logger.warning("VL_REBUILD failed: %s", exc)
            return None

    async def _load_ocr_strategies(self, db) -> set[str] | None:
        """从 DB 读取 ocr_strategy_* 配置，返回启用的策略名称集合。
        None = 默认全部启用（无 DB 时）。
        """
        if not db:
            return None
        try:
            from app.services.admin_ai_config_service import get_all_configs

            cfg = await get_all_configs(db)
        except Exception:
            return None

        strategy_map = {
            "math_formula": "ocr_strategy_math_formula",
            "punctuation": "ocr_strategy_punctuation",
            "digit_letter": "ocr_strategy_digit_letter",
            "space_newline": "ocr_strategy_space_newline",
        }
        enabled = set()
        for name, cfg_key in strategy_map.items():
            val = cfg.get(cfg_key) if cfg else None
            if val is None or str(val).lower() == "true":
                enabled.add(name)
        return enabled

    async def _load_structure_features_async(self, db) -> dict[str, bool]:
        """从 DB 读取 ocr_structure_* 配置，返回 feature flags 字典。"""
        features = {"question_type": True, "options": True, "answer": True, "analysis": True}
        if not db:
            return features
        try:
            from app.services.admin_ai_config_service import get_all_configs

            cfg = await get_all_configs(db)
        except Exception:
            return features
        feature_map = {
            "question_type": "ocr_structure_question_type",
            "options": "ocr_structure_options",
            "answer": "ocr_structure_answer",
            "analysis": "ocr_structure_analysis",
        }
        for name, cfg_key in feature_map.items():
            val = cfg.get(cfg_key) if cfg else None
            if val is not None and str(val).lower() == "false":
                features[name] = False
        return features

    async def _run_ocr_correction(self, normalized_blocks: list[dict], options: dict | None = None, **_kw) -> dict:
        """Stage 1.5: AI OCR text correction via multi-model router (PaddleOCR-VL → DeepSeek → rule)."""
        opts = options or {}
        db = _kw.get("db")

        # 合并流水线跳过 AI 纠错：单图文本已纠错，合并只需重新切分+匹配
        if opts.get("skip_ocr_correction"):
            logger.info(
                "【OCR-4】skip_ocr_correction | blocks=%d — 合并流水线复用单图纠错结果",
                len(normalized_blocks),
            )
            return {"normalized_blocks": normalized_blocks, "ocr_correction_diagnostics": {}}

        logger.info(
            "【OCR-4】ocr_correction router | blocks=%d",
            len(normalized_blocks),
        )
        kw = {k: v for k, v in _kw.items() if k != "db"}
        return await self._run_ocr_correction_router(
            normalized_blocks, opts, db, **kw,
        )

    async def _run_ocr_correction_router(
        self, normalized_blocks: list[dict], opts: dict, db, **_kw,
    ) -> dict:
        """通过 OCRFixRouter 执行多模型 OCR 纠错。"""
        from app.features.ocr_fix import OCRFixRouter
        from app.features.ocr_fix.metrics import OcrCorrectionMetrics

        # 构建 router 配置
        router_config = await self._build_router_config(opts, db)

        router = OCRFixRouter()
        router.configure(router_config)

        # 页面图像由 run() 预渲染后传入，避免 chunked 模式重复渲染
        page_images = _kw.get("page_images")

        metrics = OcrCorrectionMetrics()

        corrections: list[dict] = []
        corrected_blocks: list[dict] = [None] * len(normalized_blocks)  # type: ignore
        stats = {
            "total_blocks": len(normalized_blocks),
            "noisy_blocks": 0,
            "corrected_blocks": 0,
            "skipped_blocks": 0,
            "model_used": "",
        }
        quality_gate_shadow_records: list[dict] = []

        # Phase 1: classify blocks and collect correction candidates
        to_correct: list[tuple[int, dict, str, float, float]] = []
        for idx, block in enumerate(normalized_blocks):
            text = str(block.get("normalized_text") or "")
            if not text.strip():
                corrected_blocks[idx] = block
                continue

            noise_score = _detect_noise(block)
            structure_score = _detect_structure_abnormal(text)
            has_image = bool(page_images)
            should = _should_correct(noise_score, router_config, structure_score=structure_score, has_image=has_image)

            if not should:
                corrected_blocks[idx] = block
                stats["skipped_blocks"] += 1
                corrections.append({
                    "block_index": block.get("block_index", 0),
                    "page": block.get("page", 1),
                    "noise_score": round(noise_score, 3),
                    "structure_score": round(structure_score, 3),
                    "corrected": False,
                })
                continue

            stats["noisy_blocks"] += 1
            to_correct.append((idx, block, text, noise_score, structure_score))

        metrics.record_classification(
            total=stats["total_blocks"],
            noisy=stats["noisy_blocks"],
            skipped=stats["skipped_blocks"],
        )

        # Phase 2: concurrent fix (same pattern as legacy path)
        from app.features.token_budget import estimate_tokens as _est, check_token_limit, record_token_usage

        sem = asyncio.Semaphore(3)

        from types import SimpleNamespace as _FixResult

        async def _fix_one(idx: int, block: dict, text: str):
            async with sem:
                estimated = _est(text) * 3
                if not await check_token_limit(estimated, router_config):
                    return idx, _FixResult(
                        fixed_text=text,
                        model_used="skipped_budget",
                        raw_response="token_limit",
                        confidence=None,
                        tokens_used=None,
                        duration_ms=None,
                        risk_flags=None,
                        safety=None,
                    )

                page_num = block.get("page", 1)
                page_image = page_images.get(page_num) if page_images else None
                logger.info(
                    "【OCR-4】AI纠错输入 | block=%d page=%s noise=%.3f structure=%.3f %s",
                    idx, page_num,
                    _detect_noise(block), _detect_structure_abnormal(text),
                    safe_text_preview(text),
                )
                has_options = bool(re.search(r"[A-D][.、．）)\s]", text))
                result = await router.fix(
                    image=page_image,
                    ocr_text=text,
                    context={"block_index": idx, "page": page_num, "entry_point": "ocr_correction_router",
                             "has_options": has_options},
                )

                if result.tokens_used:
                    await record_token_usage(result.tokens_used)

                return idx, result

        fix_results = await asyncio.gather(
            *[_fix_one(idx, block, text) for idx, block, text, _, _ in to_correct],
            return_exceptions=True,
        )

        # Phase 3: process results
        for (idx, block, text, noise_score, structure_score), fix_result in zip(to_correct, fix_results):
            if isinstance(fix_result, BaseException):
                logger.warning("router fix block %d failed: %s", idx, fix_result)
                corrected_blocks[idx] = block
                corrections.append({
                    "block_index": block.get("block_index", 0),
                    "page": block.get("page", 1),
                    "noise_score": round(noise_score, 3),
                    "structure_score": round(structure_score, 3),
                    "corrected": False,
                    "reason": f"exception: {fix_result}",
                    "before_preview": _safe_text_summary(text),
                })
                metrics.record_failure(model="exception", before=text)
                continue

            _, result = fix_result
            new_block = dict(block)

            # PaddleOCR-VL may return confidence=0.0 when the API doesn't
            # provide per-document confidence — treat VL results as valid
            # regardless of confidence value.
            is_vl = "paddleocr-vl" in (result.model_used or "")
            if result.fixed_text != text and (result.confidence and result.confidence > 0 or is_vl):
                # ---- AI safety gate: use unified CandidateEvaluator ----
                from app.features.candidate_evaluator import (
                    CandidateDecision,
                    get_evaluator,
                )

                if is_vl and not result.confidence:
                    logger.info(
                        "VL result submitted to safety gate (conf=0.0, text_len=%d)",
                        len(result.fixed_text),
                    )
                evaluation = get_evaluator().evaluate(
                    original_text=text,
                    candidate_text=result.fixed_text,
                    context={
                        "has_options": bool(re.search(r"[A-D][.、．）)\s]", text)),
                        "stem_context": text[:200],
                    },
                    quality_report={
                        "low_confidence": noise_score > 0.3,
                        "garbled_detected": structure_score > 0.2,
                    },
                    provenance={
                        "engine": result.model_used or "",
                        "model_version": result.model_used or "",
                    },
                )

                # ── Domain Quality Gate shadow evaluation ──
                if _get_domain_quality_gate_mode() in ("shadow", "enforce"):
                    try:
                        from app.features.quality_gate import (
                            CompositeQualityGate,
                            QualityContext as QGateContext,
                            record_shadow_decision as _record_qgate,
                        )
                        _qgate = CompositeQualityGate()
                        _qctx = QGateContext(
                            pipeline_fingerprint=self.pipeline_id or "ocr_correction",
                            gate_mode=_get_domain_quality_gate_mode(),
                            existing_decision="accept",
                            doc_ir_source=result.model_used or "unknown",
                        )
                        _qdecisions = _qgate.evaluate(text, result.fixed_text, _qctx)
                        for _qd in _qdecisions:
                            entry = _record_qgate(_qd, _qctx)
                            entry["candidate_index"] = idx
                            entry["page"] = block.get("page", 1)
                            quality_gate_shadow_records.append(entry)
                    except Exception as _qexc:
                        logger.warning(
                            "[QUALITY-GATE] shadow evaluation failed: %s", _qexc,
                        )

                accepted = evaluation.decision == CandidateDecision.ACCEPT
                safe_text = evaluation.accepted_text or text
                reason_code = evaluation.reason_code
                risk_flags = evaluation.risk_flags
                diff = evaluation.diff

                # Build compat trace dict for existing consumers
                safety_dict = {
                    "stage": "ocr_fix",
                    "model": result.model_used,
                    "before": text[:500],
                    "after": safe_text[:500],
                    "diff": diff,
                    "risk_flags": risk_flags,
                    "accepted": accepted,
                    "rollback_reason": reason_code if not accepted else None,
                    "tokens_used": result.tokens_used or 0,
                    "duration_ms": getattr(result, "duration_ms", None) or 0,
                }

                if accepted:
                    new_block["normalized_text"] = safe_text
                    new_block["ocr_correction_applied"] = True
                    new_block["ocr_fix_model"] = result.model_used
                    stats["corrected_blocks"] += 1

                    logger.info(
                        "【OCR-5】AI纠错输出 | block=%d page=%d model=%s conf=%.2f\n"
                        "  └─ 纠错前: %.160s\n  └─ 纠错后: %.160s",
                        idx, block.get("page", 1), result.model_used, result.confidence,
                        text, safe_text,
                    )
                    metrics.record_correction(
                        model=result.model_used,
                        before=text,
                        after=safe_text,
                        duration_ms=getattr(result, "duration_ms", None),
                        tokens=result.tokens_used,
                    )
                    corrections.append({
                        "block_index": block.get("block_index", 0),
                        "page": block.get("page", 1),
                        "noise_score": round(noise_score, 3),
                        "structure_score": round(structure_score, 3),
                        "corrected": True,
                        "model_used": result.model_used,
                        "before_preview": _safe_text_summary(text),
                        "after_preview": _safe_text_summary(safe_text),
                        "safety": safety_dict,
                    })
                else:
                    # AI 修改被安全门拒绝，回滚到原文
                    logger.warning(
                        "【OCR-5-SAFETY】纠错被拒绝 | block=%d reason=%s",
                        idx, reason_code,
                    )
                    corrections.append({
                        "block_index": block.get("block_index", 0),
                        "page": block.get("page", 1),
                        "noise_score": round(noise_score, 3),
                        "structure_score": round(structure_score, 3),
                        "corrected": False,
                        "reason": f"safety_rejected: {reason_code}",
                        "model_used": result.model_used,
                        "before_preview": _safe_text_summary(text),
                        "safety": safety_dict,
                    })
            else:
                corrections.append({
                    "block_index": block.get("block_index", 0),
                    "page": block.get("page", 1),
                    "noise_score": round(noise_score, 3),
                    "structure_score": round(structure_score, 3),
                    "corrected": False,
                    "reason": result.raw_response or "no_change",
                    "before_preview": _safe_text_summary(text),
                })
                metrics.record_unchanged(
                    model=result.model_used,
                    before=text,
                )

            corrected_blocks[idx] = new_block

        # ensure all blocks are filled (defense)
        for idx, b in enumerate(corrected_blocks):
            if b is None:
                corrected_blocks[idx] = normalized_blocks[idx]

        corrected_blocks = [b for b in corrected_blocks if b is not None]

        # 敏感内容过滤
        if router_config.get("ocr_filter_sensitive", True):
            filtered_count = 0
            for b in corrected_blocks:
                text = b.get("normalized_text", "")
                filtered = _filter_sensitive(text)
                if filtered != text:
                    b["normalized_text"] = filtered
                    filtered_count += 1
            if filtered_count:
                logger.debug("ocr_filter_sensitive: filtered %d blocks", filtered_count)

        # 记录使用的模型
        used_models = {c.get("model_used") for c in corrections if c.get("model_used")}
        stats["model_used"] = ", ".join(sorted(used_models)) if used_models else "none"

        warnings: list[str] = []
        if stats["corrected_blocks"] > 0:
            warnings.append(
                f"Router corrected {stats['corrected_blocks']}/{stats['total_blocks']} blocks "
                f"(model: {stats['model_used']})"
            )

        metrics.flush(extra={
            "stats": stats,
            "used_models": sorted(used_models) if used_models else [],
        })

        return {
            "normalized_blocks": corrected_blocks,
            "ocr_correction_diagnostics": {
                "stats": stats,
                "corrections": corrections,
            },
            "quality_gate_shadow_records": quality_gate_shadow_records,
            "warnings": warnings,
        }

    async def _build_router_config(self, opts: dict, db) -> dict:
        """从 options + AdminAiModelConfig 表构建 router 配置。

        所有模型凭据均从 AdminAiModelConfig 表解析（通过 model_config_resolver），
        不依赖硬编码 env var 或 admin_ai_configs 中的独立 key。
        """
        config: dict = {
            "mode": opts.get("ocr_correction_mode", "auto"),
            "noise_threshold": opts.get("ocr_noise_threshold", 0.3),
            "daily_token_limit": opts.get("ocr_correction_daily_token_limit", 50000),
            "monthly_token_limit": opts.get("ocr_correction_monthly_token_limit", 1000000),
        }

        for key in ("ocr_fix_model", "ocr_fix_strategy"):
            val = opts.get(key)
            if val is not None:
                config[key] = val

        # 从 opts 读取过滤开关
        val = opts.get("ocr_filter_sensitive")
        if val is not None:
            config["ocr_filter_sensitive"] = str(val).lower() != "false"

        if db:
            try:
                from app.services.model_config_resolver import (
                    AIModelConfigResolver,
                    AICapability,
                )

                resolver = AIModelConfigResolver(db)

                # Resolve OCR_FIX capability — primary model (VL or DeepSeek)
                try:
                    ocr_fix_config = await resolver.resolve_for_capability(AICapability.OCR_FIX)
                    secret = await resolver.resolve_secret(ocr_fix_config)
                    provider = ocr_fix_config.provider

                    if provider == "deepseek":
                        config["deepseek_api_key"] = secret
                        if ocr_fix_config.endpoint:
                            config["deepseek_base_url"] = ocr_fix_config.endpoint
                    elif provider in ("paddleocr-vl", "paddleocr_vl"):
                        config["paddleocr_vl_api_token"] = secret
                        if ocr_fix_config.endpoint:
                            config["paddleocr_vl_base_url"] = ocr_fix_config.endpoint
                        config["paddleocr_vl_model"] = ocr_fix_config.model_name
                    else:
                        # Unknown provider → assume PaddleOCR-VL compatible
                        config["paddleocr_vl_api_token"] = secret
                        if ocr_fix_config.endpoint:
                            config["paddleocr_vl_base_url"] = ocr_fix_config.endpoint
                        config["paddleocr_vl_model"] = ocr_fix_config.model_name
                except ValueError:
                    logger.info("OCR router: no OCR_FIX config resolved via AIModelConfigResolver")

                # DeepSeek fallback for auto chain (if primary is not DeepSeek)
                if "deepseek_api_key" not in config:
                    try:
                        ds_config = await resolver.resolve_for_capability(AICapability.AI_REPAIR)
                        if ds_config.provider == "deepseek":
                            config["deepseek_api_key"] = await resolver.resolve_secret(ds_config)
                            if ds_config.endpoint:
                                config["deepseek_base_url"] = ds_config.endpoint
                    except ValueError:
                        logger.info("OCR router: no AI_REPAIR fallback config resolved")
            except Exception:
                logger.warning("OCR router: AIModelConfigResolver failed", exc_info=True)

            # 从 DB admin_ai_configs 读取过滤配置
            try:
                from app.services.admin_ai_config_service import get_all_configs
                db_configs = await get_all_configs(db)
                for key in ("ocr_filter_sensitive", "ocr_filter_max_chars", "ocr_filter_max_tokens"):
                    val = db_configs.get(key)
                    if val is not None:
                        if isinstance(val, bool):
                            config[key] = val
                        else:
                            config[key] = str(val).lower() != "false" if key == "ocr_filter_sensitive" else val
            except Exception:
                logger.warning("OCR router: admin_ai_configs read failed", exc_info=True)

        # DeepSeek env var fallback for backward compat only
        import os
        if "deepseek_api_key" not in config:
            config["deepseek_api_key"] = os.environ.get("DEEPSEEK_API_KEY", "")

        return config

    async def _run_analyze_structure(self, normalized_blocks: list[dict], **_kw) -> dict:
        """Stage 2: detect question/answer document layout."""
        db = _kw.get("db")
        features = await self._load_structure_features_async(db)
        has_boxes = any(
            b.get("boxes") and len(b["boxes"]) > 0
            for b in (normalized_blocks or [])
        )
        if has_boxes:
            doc_ir = _get_blocks_document_ir(normalized_blocks)
            if doc_ir is not None:
                from app.features.structure_analyzer import analyze_structure_from_ir
                structure = analyze_structure_from_ir(doc_ir, features=features)
            else:
                structure = analyze_structure(normalized_blocks, features=features)
        else:
            structure = analyze_structure(normalized_blocks, features=features)

        # In AUTO mode, refine import mode based on structure analysis
        import_mode = _kw.get("import_mode")
        source_file = _kw.get("source_file", "")
        if import_mode == ImportMode.AUTO:
            detected = detect_import_mode(source_file, structure)
            strategy = get_strategy(detected)
            return {
                "structure": structure,
                "import_mode": detected,
                "strategy": strategy,
                "warnings": [f"auto-detected import_mode: {detected.value}"],
            }

        return {"structure": structure, "warnings": []}

    def _run_classify_pages(self, normalized_blocks: list[dict], structure: dict | None = None, **_kw) -> dict:
        """Stage 2.5: classify each page and filter out non-question pages."""
        from app.core.config import settings

        strategy = _kw.get("strategy") or {}

        if not settings.PAGE_CLASSIFIER_ENABLED and not strategy.get("page_classifier_enabled"):
            return {"page_classifications": [], "warnings": ["page classifier disabled"]}

        doc_ir = _get_blocks_document_ir(normalized_blocks)
        section_markers = structure.get("section_markers") if structure else None

        if doc_ir is not None:
            from app.features.page_classifier import classify_pages_from_ir
            page_classifications = classify_pages_from_ir(doc_ir, section_markers=section_markers)
        else:
            page_classifications = classify_pages(normalized_blocks, section_markers=section_markers)

        # Apply mode-specific filtering rules
        filter_knowledge = strategy.get("filter_knowledge_pages", True)
        filter_catalog = strategy.get("filter_catalog_pages", True)

        allowed_labels = {"QUESTION_PAGE", "ANSWER_PAGE", "ANALYSIS_PAGE"}
        if not filter_knowledge:
            allowed_labels.add("KNOWLEDGE_PAGE")
        if not filter_catalog:
            allowed_labels.add("CATALOG_PAGE")

        filtered = filter_blocks_by_classification(
            normalized_blocks, page_classifications, allowed_labels=allowed_labels,
        )

        warnings: list[str] = []
        removed_pages = len(normalized_blocks) - len(filtered)
        if removed_pages:
            label_summary = {}
            for pc in page_classifications:
                label_summary[pc["label"]] = label_summary.get(pc["label"], 0) + 1
            warnings.append(
                f"page_classifier: {removed_pages} blocks filtered, "
                f"page types: {label_summary}"
            )

        return {
            "normalized_blocks": filtered,
            "page_classifications": page_classifications,
            "warnings": warnings,
        }

    def _run_structure_freeze(
        self,
        normalized_blocks: list[dict],
        **_kw,
    ) -> dict:
        """Stage 3: detect and freeze option structures before splitting.

        Supports four modes via STRUCTURE_FREEZE_MODE env var:
          - ``legacy`` (default): pure block-based detection via
            ``run_structure_freeze_stage``. Current behavior, unchanged.
          - ``dual``: runs both legacy and DocumentIR-based freeze, compares
            results, logs differences. Legacy output drives production.
          - ``ir``: DocumentIR-based freeze as single source of truth.
            Falls back to legacy when DocumentIR is unavailable.
          - ``ir_canary``: IR-driven freeze with failover to legacy when
            canary conditions are triggered. Legacy runs simultaneously
            as control. Diagnostics include canary failover trace.

        Downstream stages read ``frozen_option_registry`` (always in
        legacy-compatible format). In ``dual``/``ir``/``ir_canary`` mode, additional
        diagnostics are attached under ``freeze_dual_diagnostics`` /
        ``freeze_ir_warnings``.
        """
        freeze_mode = _get_structure_freeze_mode()

        # ── Always run legacy freeze ──
        legacy_result = run_structure_freeze_stage(normalized_blocks)
        legacy_registry = legacy_result.get("frozen_option_registry", {})

        if freeze_mode == "legacy":
            return legacy_result

        # ── Dual / IR: attempt DocumentIR-based freeze ──
        doc_ir = _get_blocks_document_ir(normalized_blocks)
        ir_result: dict = {}
        ir_registry_raw: dict[str, list] = {}

        if doc_ir is not None:
            try:
                from app.features.pipeline_stages.structure_freeze_stage import (
                    freeze_from_document_ir as _ir_freeze,
                    freeze_registry_to_block_format as _ir_to_legacy,
                )

                ir_result = _ir_freeze(doc_ir)
                ir_registry_raw = ir_result.get("frozen_option_registry", {})
            except Exception as exc:
                logger.warning(
                    "[FREEZE] IR freeze failed, falling back: %s", exc,
                )
                ir_result = {"warnings": [f"ir_freeze_error: {exc}"]}

        # ── IR-mode specific ──
        if freeze_mode == "ir":
            if not ir_registry_raw:
                logger.warning(
                    "[FREEZE] IR mode: registry empty, falling back to legacy"
                )
                result = dict(legacy_result)
                ir_warns = ir_result.get("warnings", [])
                result["warnings"] = list(
                    dict.fromkeys(
                        result.get("warnings", [])
                        + ir_warns
                        + ["freeze_ir_empty_fallback_legacy"]
                    )
                )
                result["freeze_mode"] = "ir"
                result["freeze_ir_warnings"] = ir_warns
                result["freeze_ir_empty"] = True
                return result

            # Convert IR registry to legacy-compatible format
            from app.features.pipeline_stages.structure_freeze_stage import (
                _freeze_deep_freeze,
                freeze_registry_to_block_format as _ir_to_legacy,
            )

            legacy_compat = _freeze_deep_freeze(_ir_to_legacy(ir_registry_raw))

            return {
                "frozen_option_registry": legacy_compat,
                "frozen_option_registry_ir": ir_registry_raw,
                "frozen_structures": ir_result.get("frozen_structures", []),
                "freeze_checksum": ir_result.get("freeze_checksum", ""),
                "freeze_mode": "ir",
                "freeze_ir_warnings": ir_result.get("warnings", []),
                "warnings": list(
                    dict.fromkeys(
                        legacy_result.get("warnings", [])
                        + ir_result.get("warnings", [])
                    )
                ),
            }

        # ── IR Canary mode: IR-driven, with failover to legacy ──
        if freeze_mode == "ir_canary":
            from app.features.ocr_canary import (
                check_ir_canary_failover,
                is_canary_globally_disabled,
                is_ir_canary_disabled,
            )

            # Check kill-switches before running canary logic
            if is_canary_globally_disabled() or is_ir_canary_disabled():
                logger.info(
                    "[FREEZE] IR canary: disabled via kill-switch, falling back to legacy"
                )
                return legacy_result

            # Compute comparison once, reuse results
            _cmp = _compare_freeze_results(
                legacy_result, ir_result,
                legacy_registry, ir_registry_raw,
            )

            should_fallback, failover_reasons = check_ir_canary_failover(
                doc_ir_available=doc_ir is not None,
                ir_registry_nonempty=bool(ir_registry_raw),
                legacy_registry_nonempty=bool(legacy_registry),
                option_key_match=_cmp.get("option_key_match", False),
                binding_lost_count=_cmp.get("binding_lost_count", 0),
                exception_occurred=bool(
                    any(
                        w.startswith("ir_freeze_error")
                        for w in ir_result.get("warnings", [])
                    )
                ),
            )

            if should_fallback or not ir_registry_raw:
                logger.warning(
                    "[FREEZE] IR canary: fallback to legacy, reasons=%s",
                    failover_reasons,
                )
                result = {**legacy_result}
                result["freeze_mode"] = "ir_canary"
                result["freeze_canary_fallback"] = True
                result["freeze_canary_fallback_reasons"] = failover_reasons
                result["freeze_ir_warnings"] = ir_result.get("warnings", [])
                result["warnings"] = list(
                    dict.fromkeys(
                        result.get("warnings", [])
                        + ir_result.get("warnings", [])
                        + ["freeze_ir_canary_fallback_legacy"]
                    )
                )
                return result

            # IR-driven result with dual comparison
            import types
            from app.features.pipeline_stages.structure_freeze_stage import (
                _freeze_deep_freeze,
            )

            legacy_compat = _ir_to_legacy(ir_registry_raw)

            return {
                "frozen_option_registry": _freeze_deep_freeze(legacy_compat),
                "frozen_option_registry_ir": ir_registry_raw,
                "frozen_structures": ir_result.get("frozen_structures", []),
                "freeze_checksum": ir_result.get("freeze_checksum", ""),
                "freeze_mode": "ir_canary",
                "freeze_canary_fallback": False,
                "freeze_dual_diagnostics": _cmp,
                "freeze_ir_warnings": ir_result.get("warnings", []),
                "warnings": list(
                    dict.fromkeys(
                        legacy_result.get("warnings", [])
                        + ir_result.get("warnings", [])
                    )
                ),
            }

        # ── Dual mode: compare and log ──
        if freeze_mode == "dual":
            dual_diagnostics = _compare_freeze_results(
                legacy_result, ir_result,
                legacy_registry, ir_registry_raw,
            )

            logger.info(
                "[FREEZE-DUAL] legacy=%d opt, ir=%d opt, "
                "key_match=%s, text_match=%s, binding_lost=%d, diffs=%d",
                dual_diagnostics["legacy_option_count"],
                dual_diagnostics["ir_option_count"],
                dual_diagnostics["option_key_match"],
                dual_diagnostics["option_text_match"],
                dual_diagnostics["binding_lost_count"],
                dual_diagnostics["differences_count"],
            )

            if dual_diagnostics["differences_count"] > 0:
                for diff in dual_diagnostics["differences"][:10]:
                    logger.info(
                        "[FREEZE-DUAL] diff: %s key=%s legacy=%.40s ir=%.40s",
                        diff["type"], diff.get("option_key", "?"),
                        diff.get("legacy_text", ""), diff.get("ir_text", ""),
                    )

            result = dict(legacy_result)
            result["freeze_mode"] = "dual"
            result["freeze_dual_diagnostics"] = dual_diagnostics
            result["freeze_ir_warnings"] = ir_result.get("warnings", [])
            return result

        # ── Unknown freeze_mode: warn and fall back to legacy ──
        logger.warning(
            "[FREEZE] Unknown freeze_mode=%r, falling back to legacy",
            freeze_mode,
        )
        return legacy_result

    def _run_split(self, normalized_blocks: list[dict], structure: dict | None = None, **_kw) -> dict:
        """Stage 4: split text blocks into individual questions.

        P2-3 / P1-3: when running in chunked mode, ``_kw`` may include
        ``_chunk_seen_hashes`` (a mutable set of overlap-dedup hashes
        already written by earlier chunks) and ``_chunk_logical_end``
        (the chunk's own last page; anything past that is overlap
        territory). The hash is computed via ``_compute_overlap_hash``
        — same payload normalization as ``review_service`` /
        ``QuestionImport.question_hash`` — so OCR jitter on the
        question *number* (e.g. ``1`` vs ``I``) no longer causes
        spurious retains, and section-reset numbers (``1, 2, …``
        appearing twice in one PDF) no longer cause spurious drops.
        Questions whose hash is already in seen_hashes AND whose
        ``page_start`` falls inside the overlap region are dropped here
        so review never sees them. Hashes we keep are added to the set
        so the next chunk sees this update.

        Boundary check: if the chunk's last kept question is within ±1 page
        of ``_chunk_logical_end`` AND its option_lines contain A/B/C but
        miss both D and E, we emit a ``chunk_boundary_unclosed`` warning
        — heuristic for "4-option MCQ truncated by chunk edge" only.
        Two-option / true-false / short-answer questions don't trip this.
        """
        strategy = _kw.get("strategy") or {}
        gap_tolerance = strategy.get("question_number_gap_tolerance", 10)
        # P1-1: 透传 import_mode（统一为小写字符串）给 splitter，
        # 让 book 模式的"软 prose" 检测能给可疑题打 book_pdf_prose_like flag。
        # 其它模式不受影响。
        raw_im = _kw.get("import_mode")
        if isinstance(raw_im, ImportMode):
            import_mode_str = raw_im.value
        else:
            import_mode_str = str(raw_im or "").lower() or None

        split_blocks = normalized_blocks
        warnings: list[str] = []
        _run_split_data: dict[str, Any] = {}

        # ── Cross-page linking: merge content from linked pages ──
        xp_blocks, xp_links, xp_warnings, xp_merge_results = _merge_cross_page_blocks(split_blocks)
        if xp_links:
            split_blocks = xp_blocks
            warnings.extend(xp_warnings)
            warnings.append(f"cross_page: {len(xp_links)} link(s) applied")
            _run_split_data["cross_page_merge_results"] = xp_merge_results

        layout_filter_diagnostics = {
            "enabled": False,
            "pages_considered": 0,
            "filtered_line_count": 0,
            "kept_line_count": 0,
            "region_signals": [],
        }
        if (
            import_mode_str == "book"
            and str(_kw.get("source_type") or "").lower() == "pdf"
            and any(b.get("boxes") for b in normalized_blocks)
        ):
            try:
                from app.features.visual_boundary_detector import filter_book_layout_blocks_from_ir

                doc_ir = _get_blocks_document_ir(normalized_blocks)
                if doc_ir is not None:
                    split_blocks, layout_filter_diagnostics = filter_book_layout_blocks_from_ir(doc_ir)
                else:
                    split_blocks, layout_filter_diagnostics = normalized_blocks, {"error": "no_document_ir"}
            except Exception as exc:
                logger.warning("book layout filter failed: %s", exc)

        layout_result = _kw.get("layout_result") or {}
        split_mode = _kw.get("split_mode", "standard")
        frozen_option_registry: dict = _kw.get("frozen_option_registry") or {}

        # ── VL_REBUILD: 结构失败，尝试用 PaddleOCR-VL 重建 blocks ──
        if split_mode == "vl_rebuild":
            file_path = _kw.get("file_path")
            vl_config = _kw.get("vision_config")
            if file_path and vl_config:
                logger.info(
                    "VL_REBUILD: restructuring blocks via PaddleOCR-VL "
                    "(source=%s, confidence=%.2f, opt_failed=%s)",
                    _kw.get("source_type", "unknown"),
                    layout_result.get("layout_confidence", 1.0),
                    layout_result.get("option_detection_failed", False),
                )
                rebuilt = self._run_vl_rebuild_blocks(
                    file_path, normalized_blocks, vl_config,
                    original_raw_text=_kw.get("_original_raw_text", ""),
                )
                if rebuilt:
                    split_blocks = rebuilt
                    # VL rebuild: preserve frozen option registry via text match
                    # instead of clearing it (OCR-103 VL rebuild fix)
                    old_registry = frozen_option_registry
                    split_mode = "standard"
                    layout_result = {}
                    if old_registry:
                        remap_result = _remap_frozen_registry_vl_rebuild(
                            old_registry, rebuilt,
                        )
                        frozen_option_registry = remap_result.get("registry", {})
                        binding_lost_qs = remap_result.get("binding_lost_questions", [])
                        if binding_lost_qs:
                            logger.warning(
                                "[FREEZE] VL rebuild: %d questions with binding_lost: %s",
                                len(binding_lost_qs), binding_lost_qs,
                            )
                        if frozen_option_registry:
                            preserved = sum(
                                1 for q in frozen_option_registry.values()
                                if not isinstance(q, list)
                                or not any(
                                    getattr(e, 'binding_status', '') == 'binding_lost'
                                    for e in q
                                )
                            )
                            logger.info(
                                "[VL-REBUILD] preserved frozen registry: "
                                "%d questions with bindings",
                                preserved,
                            )
                    else:
                        frozen_option_registry = None
                    warnings.append(
                        f"vl_rebuild: restructured {len(rebuilt)} blocks via PaddleOCR-VL"
                    )
                else:
                    split_mode = "layout_enhanced"
                    warnings.append(
                        "vl_rebuild: PaddleOCR-VL restructuring unavailable, "
                        "falling back to layout_enhanced"
                    )
            else:
                split_mode = "layout_enhanced"
                warnings.append(
                    "vl_rebuild: file_path or vl_config missing, "
                    "falling back to layout_enhanced"
                )

        raw_questions = split_questions(
            split_blocks,
            structure=structure,
            gap_tolerance=gap_tolerance,
            import_mode=import_mode_str,
            layout_result=layout_result if layout_result.get("option_groups") else None,
            split_mode=split_mode,
            frozen_option_registry=frozen_option_registry,
        )

        text_blocks = [
            b for b in split_blocks
            if str(b.get("normalized_text") or "").strip()
        ]
        split_diagnostics = {
            "normalized_block_count": len(normalized_blocks),
            "text_block_count": len(text_blocks),
            "raw_question_count": len(raw_questions),
            "split_mode": split_mode,
            "book_prose_downgraded": sum(
                1 for q in raw_questions
                if "book_pdf_prose_like" in (q.get("risk_flags") or [])
            ),
            "layout_filter": layout_filter_diagnostics,
            "raw_questions_hash": _safe_hash_preview(raw_questions),
            "failure_reason": None,
        }

        def _filter_book_pdf_prose() -> None:
            nonlocal raw_questions
            if (
                not raw_questions
                or not _is_book_import_mode(_kw.get("import_mode"))
                or str(_kw.get("source_type") or "").lower() != "pdf"
            ):
                return
            kept_questions = []
            prose_skipped = 0
            prose_preview: list[dict] = []
            for question in raw_questions:
                if _looks_like_book_pdf_prose_candidate(question):
                    prose_skipped += 1
                    if len(prose_preview) < 20:
                        import hashlib
                        raw_text = str(question.get("raw_question_text") or "")
                        prose_preview.append({
                            "page": question.get("page_start"),
                            "number": question.get("number"),
                            "text_hash": hashlib.md5(raw_text.encode()).hexdigest()[:12],
                            "text_len": len(raw_text),
                        })
                    continue
                kept_questions.append(question)
            if prose_skipped:
                raw_questions = kept_questions
                warnings.append(f"book_pdf_prose_skipped: {prose_skipped}")
                split_diagnostics["book_pdf_prose_skipped"] = (
                    split_diagnostics.get("book_pdf_prose_skipped", 0) + prose_skipped
                )
                split_diagnostics["prose_skipped_count"] = (
                    split_diagnostics.get("prose_skipped_count", 0) + prose_skipped
                )
                split_diagnostics.setdefault("prose_skipped_preview", []).extend(prose_preview)
                split_diagnostics["raw_question_count_after_prose_filter"] = len(raw_questions)

        def _record_book_pdf_prose_from_blocks() -> None:
            if (
                raw_questions
                or not _is_book_import_mode(_kw.get("import_mode"))
                or str(_kw.get("source_type") or "").lower() != "pdf"
            ):
                return
            previews: list[dict] = []
            for block in text_blocks:
                text = str(block.get("normalized_text") or "").strip()
                first_line = text.split("\n", 1)[0].strip()
                match = re.match(r"^(\d+)\s*[.．、]\s*", first_line)
                if not match:
                    continue
                if _BOOK_PDF_QUESTION_SIGNAL_RE.search(text) or re.search(r"(?:^|\n)\s*[A-D]\s*[.．、:：)）]", text):
                    continue
                marker_count = len(_BOOK_PDF_PROSE_MARKER_RE.findall(text))
                sentence_count = len(_BOOK_PDF_SENTENCE_END_RE.findall(text))
                if marker_count < 2 or sentence_count < 2:
                    continue
                previews.append({
                    "page": block.get("page"),
                    "number": int(match.group(1)),
                    "text": re.sub(r"\s+", " ", text)[:80],
                })
                if len(previews) >= 20:
                    break
            if previews:
                split_diagnostics["prose_skipped_count"] = len(previews)
                split_diagnostics["prose_skipped_preview"] = previews

        _filter_book_pdf_prose()
        _record_book_pdf_prose_from_blocks()

        if not raw_questions:
            if text_blocks:
                # 尝试视觉边界检测（需要 boxes 数据）
                has_boxes = any(b.get("boxes") for b in normalized_blocks)
                if has_boxes:
                    try:
                        from app.features.visual_boundary_detector import detect_visual_boundaries_from_ir

                        doc_ir = _get_blocks_document_ir(split_blocks)
                        if doc_ir is not None:
                            visual_bounds = detect_visual_boundaries_from_ir(doc_ir)
                        else:
                            visual_bounds = []
                        from app.features.question_splitter import split_by_visual_boundaries
                        split_diagnostics["visual_boundary"] = {
                            "boundary_count": len(visual_bounds),
                            "boundaries": [
                                {
                                    "page": b.get("page"),
                                    "signal": b.get("signal"),
                                    "preview": _visual_boundary_preview(split_blocks, b),
                                }
                                for b in visual_bounds[:20]
                            ],
                        }
                        if len(visual_bounds) >= 2:
                            raw_questions = split_by_visual_boundaries(split_blocks, visual_bounds)
                            warnings.append(f"visual_boundary: split {len(raw_questions)} questions via bbox")
                            split_diagnostics["failure_reason"] = None
                            split_diagnostics["fallback_created"] = False
                            split_diagnostics["detection_method"] = "visual_boundary"
                            _filter_book_pdf_prose()
                    except Exception as exc:
                        logger.warning("visual boundary detection failed: %s", exc)

                # 仍然无结果时 fallback 为单条
                if not raw_questions:
                    if _is_book_import_mode(_kw.get("import_mode")) and str(_kw.get("source_type") or "").lower() == "pdf":
                        warnings.append(
                            "no questions found in book import; skipped low-confidence fallback review item"
                        )
                        split_diagnostics["fallback_created"] = False
                        split_diagnostics["failure_reason"] = "book_text_present_but_no_question_boundary"
                        split_diagnostics["non_question_like_skipped"] = True
                    else:
                        raw_questions = [{
                            "number": 1,
                            "raw_question_text": "\n".join(
                                str(b.get("normalized_text") or "").strip() for b in text_blocks
                            ),
                            "page_start": text_blocks[0].get("page", 1),
                            "page_end": text_blocks[-1].get("page", text_blocks[0].get("page", 1)),
                            "has_options": False,
                            "option_lines": {},
                            "confidence": 0.2,
                            "risk_flags": ["fallback_low_confidence"],
                        }]
                        warnings.append("no questions found in document; created low-confidence review item")
                        split_diagnostics["fallback_created"] = True
                        split_diagnostics["failure_reason"] = "text_present_but_no_question_boundary"
            else:
                warnings.append("no questions found in document")
                split_diagnostics["fallback_created"] = False
                split_diagnostics["failure_reason"] = "no_text_blocks"
        elif len(raw_questions) < len(normalized_blocks):
            warnings.append(f"{len(normalized_blocks) - len(raw_questions)} blocks produced no questions")
            split_diagnostics["fallback_created"] = False
            split_diagnostics["failure_reason"] = None
        else:
            split_diagnostics["fallback_created"] = False
            split_diagnostics["failure_reason"] = None

        # P2-3 / P1-3: chunk overlap dedup + boundary unclosed warning.
        # Only kicks in when called from the chunked runner via opts.
        seen_hashes: set | None = _kw.get("_chunk_seen_hashes")
        logical_end: int | None = _kw.get("_chunk_logical_end")
        if seen_hashes is not None and logical_end is not None:
            kept: list[dict] = []
            skipped_numbers: list[int] = []
            for q in raw_questions:
                page_start = q.get("page_start") or 0
                qhash = _compute_overlap_hash(q)
                # Drop only if both: (1) hash was already written by a
                # previous chunk AND (2) the question lives in our overlap
                # zone (page_start > logical_end). Without the page check
                # we would also drop legitimate non-overlap hash collisions
                # (e.g. user pasted same MCQ twice in one PDF).
                if (
                    qhash is not None
                    and qhash in seen_hashes
                    and page_start > logical_end
                ):
                    num = q.get("number")
                    if num is not None:
                        skipped_numbers.append(num)
                    else:
                        skipped_numbers.append(-1)
                    continue
                kept.append(q)
                if qhash is not None:
                    seen_hashes.add(qhash)

            if skipped_numbers:
                warnings.append(
                    f"boundary_overlap_skipped: {sorted(set(skipped_numbers))}"
                )
                split_diagnostics["overlap_skipped_numbers"] = sorted(set(skipped_numbers))
            raw_questions = kept

            # Boundary unclosed: P1-2 收紧为"明显被截断的 4 选题"才警告，
            # 避免对 A/B 双选 / A/C 判断 / 简答题误报。条件：
            # (1) 末题 page_end 距 chunk logical_end ≤ 1 页（贴合边界）
            # (2) has_options=True
            # (3) A/B/C 全部出现但 D/E 都缺 → 像 4 选项被截断
            if raw_questions:
                last = raw_questions[-1]
                last_page_end = last.get("page_end") or 0
                opts = last.get("option_lines") or {}
                opt_keys = {str(k).upper() for k in opts.keys()}
                near_boundary = abs(last_page_end - logical_end) <= 1
                looks_truncated = (
                    "A" in opt_keys
                    and "B" in opt_keys
                    and "C" in opt_keys
                    and "D" not in opt_keys
                    and "E" not in opt_keys
                )
                if (
                    near_boundary
                    and bool(last.get("has_options"))
                    and looks_truncated
                ):
                    warnings.append(
                        f"chunk_boundary_unclosed: q{last.get('number')} "
                        f"may span next chunk (page_end={last_page_end}, "
                        f"logical_end={logical_end})"
                    )
                    split_diagnostics["boundary_unclosed_question"] = last.get("number")

        _log_multi_blank_stage("split", raw_questions, source_type=_kw.get("source_type"), import_mode=import_mode_str)

        # ── Apply frozen options to raw_questions (single source of truth) ──
        if frozen_option_registry:
            _apply_frozen_options(
                raw_questions, frozen_option_registry,
                freeze_checksum=_kw.get("freeze_checksum"),
                normalized_blocks=split_blocks,
            )

        # Log each parsed question
        for q in raw_questions:
            opts = q.get("option_lines") or {}
            opt_summary = ", ".join(
                f"{k}: {str(v)[:40]}" for k, v in sorted(opts.items())
            ) or "(无选项)"
            logger.info(
                "【OCR-6】题目解析结果 | number=%s page=%s has_options=%s options=%s%s\n"
                "  └─ 题干: %.200s",
                q.get("number", "?"), q.get("page_start", "?"),
                q.get("has_options", False),
                opt_summary[:120],
                " [FROZEN]" if q.get("is_frozen") else "",
                str(q.get("raw_question_text") or ""),
            )

        return {
            "raw_questions": raw_questions,
            "split_count": len(raw_questions),
            "split_diagnostics": split_diagnostics,
            "warnings": warnings,
            **_run_split_data,
        }

    def _run_question_bbox(
        self,
        raw_questions: list[dict],
        normalized_blocks: list[dict] | None = None,
        **_kw,
    ) -> dict:
        """Stage 4.5: compute question_bbox for each raw_question.

        Must run after split and before match/normalize_schema so that
        bbox fields are preserved through downstream stages.
        """
        from app.services.question_snapshot_service import (
            compute_question_bboxes_from_ir,
        )

        if not normalized_blocks:
            logger.warning("question_bbox stage: no normalized_blocks available")
            return {"raw_questions": raw_questions, "warnings": ["no_normalized_blocks"]}

        try:
            doc_ir = _get_blocks_document_ir(normalized_blocks)
            enriched = compute_question_bboxes_from_ir(raw_questions, doc_ir)
            with_bbox = sum(1 for q in enriched if q.get("question_bbox") is not None)
            logger.info("question_bbox: %d/%d got bbox", with_bbox, len(enriched))
            warnings: list[str] = []
            if with_bbox < len(enriched):
                warnings.append(f"question_bbox: {len(enriched)-with_bbox} missing bbox")
            return {"raw_questions": enriched, "warnings": warnings}
        except Exception as e:
            logger.warning("question_bbox stage failed: %s", e, exc_info=True)
            return {"raw_questions": raw_questions, "warnings": [f"question_bbox_failed: {e}"]}

    def _run_match(
        self,
        raw_questions: list[dict],
        normalized_blocks: list[dict],
        structure: dict | None = None,
        **_kw,
    ) -> dict:
        """Stage 4: match answers and explanations to questions (P5-2: delegated)."""
        has_boxes = any(
            b.get("boxes") and len(b["boxes"]) > 0
            for b in (normalized_blocks or [])
        )
        if has_boxes:
            doc_ir = _get_blocks_document_ir(normalized_blocks)
            if doc_ir is not None:
                from app.features.pipeline_stages.match_stage import run_match_stage_from_ir
                return run_match_stage_from_ir(raw_questions, doc_ir, structure=structure)
        return run_match_stage(raw_questions, normalized_blocks, structure=structure)

    def _run_normalize_schema(
        self,
        raw_questions: list[dict],
        matched: list[dict],
        source_file: str,
        source_type: str,
        subject: str | None = None,
        subject_id: int | None = None,
        **_kw,
    ) -> dict:
        """Stage 5: normalize questions to standard schema (P5-2: delegated).

        Post-stage: enforce option invariance — if ``detect_options_from_text``
        finds option patterns in the raw text but ``options`` is empty,
        emit a warning trace (not silent drop).

        This enforcement ensures that ANY path that drops options (classifier,
        splitter, freeze mismatch) is detectable in logs and diagnostics.
        """
        result = run_normalize_schema_stage(
            raw_questions, matched,
            source_file=source_file,
            source_type=source_type,
            subject=subject,
            subject_id=subject_id,
            import_mode=_kw.get("import_mode"),
            exercise_regions_missing=bool(_kw.get("exercise_regions_missing")),
        )

        # ── OPTIONS ENFORCEMENT ──
        # If detect_options_from_text(raw_text) is True but options is empty,
        # this is a pipeline bug — log a warning + attach to diagnostics.
        # blank_option_groups exemption: multi_blank_choice has empty top-level
        # options by design (options stored per-group), skip enforcement.
        questions = result.get("questions", [])
        enforce_warnings: list[str] = []
        for q in questions:
            if q.get("blank_option_groups"):
                continue
            raw_text = q.get("raw_text") or q.get("raw_question_text", "")
            if not raw_text:
                continue
            if _detect_options_from_text(raw_text):
                opts = q.get("options", [])
                if not opts:
                    qnum = q.get("number", q.get("question_index", "?"))
                    msg = (
                        f"[OPTIONS-ENFORCE] q{qnum}: detect_options_from_text=True "
                        "but options is empty — pipeline dropped detected options!"
                    )
                    logger.warning(msg)
                    enforce_warnings.append(msg)
                    # Mark the question so downstream can see the enforcement
                    existing_flags = list(q.get("risk_flags") or [])
                    q["risk_flags"] = list(dict.fromkeys(
                        existing_flags + ["options_dropped_enforcement"]
                    ))

        if enforce_warnings:
            existing_warnings = list(result.get("warnings", []))
            existing_warnings.append(
                f"options_enforcement: {len(enforce_warnings)} question(s) "
                "had detect_options=True but options empty"
            )
            result["warnings"] = existing_warnings

        return result

    async def _run_code_language_noise_clean(self, questions: list[dict], options: dict, **_kw) -> dict:
        """Stage 5.3: clean OCR code language identifier noise from question stems.

        Lightweight rule-based stage — no AI calls. Removes lines like ``(1>``,
        ``(>C``, ``C>`` that appear at natural-language-to-code transitions.
        """
        return run_code_language_noise_clean_stage(questions, options)

    async def _run_code_structure_reconstruct(self, questions: list[dict], options: dict, **_kw) -> dict:
        """Stage 5.5: reconstruct code structure for questions with code integrity issues.

        Runs between normalize_schema and classify_questions. Only processes
        questions with code integrity flags (code_brace_unbalanced, etc.).
        """
        return await run_code_structure_stage(
            questions, options,
            db=_kw.get("db"),
        )

    def _run_classify_questions(self, questions: list[dict], **_kw) -> dict:
        """Layer 1 Gate: enforce question type classification on all questions.

        Reads the ``options_classified`` field set by the Layer 1 classifier
        during ``normalize_schema``. For any question where the classifier
        determined ``has_options=False``, options are set to ``[]`` to
        enforce the SSOT rule.

        This is an enforcement gate — no re-classification occurs. All
        decisions are made by the Layer 1 classifier in
        ``question_type_classifier.classify()``.

        Returns:
            dict with ``questions``, ``question_classifications``, ``warnings``.
        """
        if not questions:
            return {"questions": [], "question_classifications": [], "warnings": []}

        enforced_count = 0
        classifications: list[dict] = []

        for q in questions:
            options_classified = q.get("options_classified", True)
            options_list = q.get("options", [])
            has_options = bool(options_list)
            question_type = q.get("question_type", "")

            entry: dict = {
                "question_number": q.get("number", q.get("question_index", "?")),
                "question_type": question_type,
                "options_classified": options_classified,
                "has_options": has_options,
                "options_count": len(options_list),
            }

            # DEFENSE: even if options_classified=False, don't clear options if
            # detect_options_from_text says raw_text has option patterns.
            # This prevents the gate from overriding the Layer 1 classifier fix.
            if not options_classified and not has_options:
                raw_text = q.get("raw_text") or q.get("raw_question_text", "")
                if raw_text and _detect_options_from_text(raw_text):
                    q["options_classified"] = True
                    options_classified = True
                    logger.info(
                        "[CLASSIFY-GATE] q%s: overrode options_classified=False→True "
                        "(detect_options_from_text=True)",
                        entry["question_number"],
                    )

            # ENFORCEMENT: if classifier said no options but options exist → clear them
            if not options_classified and options_list:
                q["options"] = []
                q["question_type"] = "subjective"
                enforced_count += 1
                entry["enforced"] = True
                entry["cleared_options"] = len(options_list)
                logger.info(
                    "[CLASSIFY-GATE] q%s: has_options=False cleared %d options "
                    "(was type=%s, now=subjective)",
                    entry["question_number"], len(options_list), question_type,
                )
            else:
                entry["enforced"] = False

            classifications.append(entry)

        warnings: list[str] = []
        if enforced_count:
            msg = (
                f"classify_gate: cleared options for {enforced_count} questions "
                "(has_options=False by Layer 1 classifier)"
            )
            warnings.append(msg)
            logger.info("[CLASSIFY-GATE] %s", msg)

        return {
            "questions": questions,
            "question_classifications": classifications,
            "warnings": warnings,
        }

    def _run_batch_validation(self, questions: list[dict], **_kw) -> dict:
        """Stage 5.6: cross-question structural integrity validation (P5-2: delegated)."""
        return run_batch_validation_stage(questions)

    def _run_batch_dedup(self, questions: list[dict], **_kw) -> dict:
        """Stage 5.5: flag batch-internal duplicates (P5-2: delegated)."""
        return run_batch_dedup_stage(questions)

    async def _run_repair(self, questions: list[dict], options: dict, **_kw) -> dict:
        """Stage 6: AI repair for low-confidence questions (P5-2: delegated)."""
        return await run_repair_stage(
            questions, options,
            db=_kw.get("db"),
            batch_validation_diagnostics=_kw.get("batch_validation_diagnostics"),
        )

    def _run_ai_validation(self, questions: list[dict], **_kw) -> dict:
        """Stage 6.2: validate AI repair results for anomalies (P5-2: delegated)."""
        return run_ai_validation_stage(questions)

    async def _run_similarity_match(
        self,
        questions: list[dict],
        db=None,
        options: dict | None = None,
        hash_index=None,
        **_kw,
    ) -> dict:
        """Stage 6.5: suggest corrections from existing question bank.

        P2-4: chunked 路径下 ``hash_index``（``GlobalHashIndex`` 实例）由
        orchestrator 注入；命中即标 ratio=1.0 强匹配，跳过 difflib 扫描。
        单 pass / 无注入时退化为旧的 subject-级 difflib fallback。
        """
        opts = options or {}
        match_config = {
            "enabled": opts.get("enable_similarity_match", True),
            "similarity_threshold": opts.get("similarity_threshold", 0.85),
        }

        result = await match_similar_questions(
            questions, db=db, config=match_config, hash_index=hash_index,
        )

        warnings: list[str] = []
        stats = result.get("stats", {})
        if stats.get("matched_count", 0) > 0:
            warnings.append(
                f"Found {stats['matched_count']} similar questions in bank "
                f"(avg ratio {stats['avg_similarity']:.2f})"
            )
        if result.get("skipped_reason"):
            warnings.append(f"Similarity match skipped: {result['skipped_reason']}")

        return {
            "questions": result["questions"],
            "similarity_match_diagnostics": {
                "stats": stats,
                "matches": result.get("matches", []),
                "skipped_reason": result.get("skipped_reason"),
            },
            "warnings": warnings,
        }

    async def _run_math_detect(
        self,
        questions: list[dict],
        **_kw,
    ) -> dict:
        """Stage 6.8: detect math candidates and apply formula risk flags (P5-2: delegated)."""
        return await run_math_detect_stage(
            questions,
            pipeline_id=self.pipeline_id,
            page_image_refs=_kw.get("page_image_refs"),
        )

    def _run_table_detect(
        self,
        questions: list[dict],
        **_kw,
    ) -> dict:
        """Stage 6.9: detect table candidates (P5-2: delegated)."""
        return run_table_detect_stage(questions)

    def _run_visual_region_detect(
        self,
        questions: list[dict],
        normalized_blocks: list | None = None,
        page_image_refs: dict | None = None,
        **_kw,
    ) -> dict:
        """Stage 6.10: page-level visual region detection from layout blocks.

        Runs after layout_router when layout blocks are available.
        Delegates to visual_region_detect_stage.
        """
        from app.features.pipeline_stages.visual_region_detect_stage import (
            run_visual_region_detect_stage,
        )
        # Build layout_blocks_by_page from normalized_blocks when available
        layout_blocks_by_page: dict[int, list[dict]] | None = None
        page_dimensions: dict[int, tuple[int, int]] | None = None
        if normalized_blocks:
            layout_blocks_by_page = {}
            page_dimensions = {}
            for block in normalized_blocks:
                page = block.get("page") or block.get("page_index") or 0
                boxes = block.get("boxes") or []
                # Collect page dimensions from the first block on each page
                if page not in page_dimensions:
                    pw = block.get("page_width") or 1000
                    ph = block.get("page_height") or 1000
                    page_dimensions[page] = (int(pw), int(ph))
                # Build layout-like entries from OCR boxes for gap analysis
                if boxes and isinstance(boxes, list):
                    layout_blocks_by_page.setdefault(page, []).extend(boxes)

        return run_visual_region_detect_stage(
            questions,
            layout_blocks_by_page=layout_blocks_by_page,
            page_dimensions=page_dimensions,
        )

    async def _run_visual_region_assign(
        self,
        questions: list[dict],
        **_kw,
    ) -> dict:
        """Stage 6.11: assign page-level visual regions to individual questions.

        Must run after split+match so question spatial bounds are available.
        Delegates to visual_region_assign_stage.
        """
        from app.features.pipeline_stages.visual_region_assign_stage import (
            run_visual_region_assign_stage,
        )

        # Collect visual_regions from questions (set by visual_region_detect)
        page_regions: dict[int, list[dict]] = {}
        for q in questions:
            for vr in (q.get("visual_regions") or []):
                if isinstance(vr, dict):
                    page = vr.get("source_page") or q.get("page_start") or 1
                    page_regions.setdefault(page, []).append(vr)

        return run_visual_region_assign_stage(
            questions,
            page_regions=page_regions,
        )

    async def _run_visual_region_crop(
        self,
        questions: list[dict],
        page_image_refs: dict | None = None,
        **_kw,
    ) -> dict:
        """Stage 6.12: crop assigned visual regions, build segments and source snapshots.

        Must run after visual_region_assign so each region knows which question it
        belongs to. Crops from page images and uploads to storage backend.

        Also generates source_snapshot_url for each question when possible.
        """
        import hashlib
        import logging
        from datetime import datetime

        logger = logging.getLogger(__name__)

        if not page_image_refs:
            for q in questions:
                flags = list(q.get("risk_flags") or [])
                if "source_snapshot_failed" not in flags:
                    flags.append("source_snapshot_failed")
                q["risk_flags"] = flags
            return {"questions": questions, "warnings": ["visual_region_crop: no page images"]}

        from app.services.storage_backend import get_storage
        from app.services.visual_region_cropper import crop_and_upload_region
        from app.services.visual_region_types import VisualRegion

        storage = get_storage()
        virtual_import_id = hashlib.md5(self.pipeline_id.encode()).hexdigest()[:8]
        month = datetime.now().strftime("%Y%m")
        crop_warnings: list[str] = []

        for q in questions:
            seen_region_ids: set[str] = set()
            segments: list[dict] = list(q.get("segments") or [])
            stem = q.get("stem") or (q.get("parsed_content") or {}).get("text") or ""

            # Process visual_regions
            vrs = list(q.get("visual_regions") or [])
            for vr_dict in vrs:
                region_id = vr_dict.get("region_id", "")
                if region_id and region_id in seen_region_ids:
                    continue
                if region_id:
                    seen_region_ids.add(region_id)

                # Reconstruct VisualRegion and crop
                from app.services.visual_region_types import (
                    CoordinateSpace, VisualRegionType, AssignmentMethod,
                )

                bbox = vr_dict.get("bbox")
                region_type_str = vr_dict.get("region_type", "unknown")
                try:
                    rt = VisualRegionType(region_type_str)
                except ValueError:
                    rt = VisualRegionType.UNKNOWN

                crs = vr_dict.get("coordinate_space", "image_pixels")
                try:
                    cs = CoordinateSpace(crs) if crs else CoordinateSpace.IMAGE_PIXELS
                except ValueError:
                    cs = CoordinateSpace.IMAGE_PIXELS

                region = VisualRegion(
                    region_id=region_id,
                    region_type=rt,
                    source_page=vr_dict.get("source_page", 1),
                    bbox=tuple(bbox) if isinstance(bbox, (list, tuple)) and len(bbox) == 4 else None,
                    coordinate_space=cs,
                    confidence=vr_dict.get("confidence", 0.5),
                    alt=vr_dict.get("alt", ""),
                    option_key=vr_dict.get("option_key"),
                )

                if region.bbox:
                    region = await crop_and_upload_region(
                        page_image_refs, region, virtual_import_id,
                    )

                if region.image_url:
                    seg = region.to_segment()
                    segments.append(seg)
                    crop_warnings.append(
                        f"visual region {region_id} cropped for page {region.source_page}"
                    )
                else:
                    flags = list(q.get("risk_flags") or [])
                    if region.crop_failed:
                        if "visual_crop_failed" not in flags:
                            flags.append("visual_crop_failed")
                    elif region.bbox is None:
                        if "visual_region_bbox_missing" not in flags:
                            flags.append("visual_region_bbox_missing")
                    q["risk_flags"] = flags

            if segments:
                q["segments"] = segments
                q["parsed_content"] = {
                    **(q.get("parsed_content") or {}),
                    "render_mode": "segments",
                    "segments": segments,
                }

            # Generate source_snapshot_url
            try:
                page = q.get("page_start") or 1
                page_path = page_image_refs.get(page) if page_image_refs else None
                if page_path:
                    q_bbox = q.get("question_bbox")
                    if q_bbox and len(q_bbox) == 4:
                        png_bytes = crop_region(
                            page_path, tuple(q_bbox),
                            coordinate_space=CoordinateSpace.IMAGE_PIXELS,
                        )
                        is_full_page = False
                    else:
                        # No question bbox — use full page as snapshot
                        from pathlib import Path
                        png_bytes = Path(page_path).read_bytes()
                        is_full_page = True

                    if png_bytes and len(png_bytes) > 0:
                        content_hash = hashlib.md5(png_bytes).hexdigest()[:12]
                        filename = f"{virtual_import_id}_snapshot_p{page}_{content_hash}.png"
                        snapshot_url = await storage.upload(
                            f"{month}/snapshots/{filename}", png_bytes,
                        )
                        if "parsed_content" not in q:
                            q["parsed_content"] = {"text": stem}
                        if isinstance(q["parsed_content"], dict):
                            q["parsed_content"]["source_snapshot_url"] = snapshot_url
                            q["parsed_content"]["source_snapshot_full_page"] = is_full_page
            except Exception as e:
                logger.warning("source_snapshot failed import=%s page=%s: %s", self.pipeline_id, page, e)
                flags = list(q.get("risk_flags") or [])
                if "source_snapshot_failed" not in flags:
                    flags.append("source_snapshot_failed")
                q["risk_flags"] = flags

        return {"questions": questions, "warnings": crop_warnings}

    async def _run_review(
        self,
        questions: list[dict],
        source_file: str,
        source_type: str,
        subject: str | None = None,
        subject_id: int | None = None,
        db=None,
        **_kw,
    ) -> dict:
        """Stage 7: submit questions to review queue (P5-2: delegated)."""
        return await run_review_stage(
            questions,
            source_file=source_file,
            source_type=source_type,
            subject=subject,
            subject_id=subject_id,
            pipeline_id=self.pipeline_id,
            db=db,
        )

    # ------------------------------------------------------------------
    # pipeline runner
    # ------------------------------------------------------------------

    async def run(
        self,
        file_content: bytes | None = None,
        source_type: str = "pdf",
        source_file: str = "",
        subject: str | None = None,
        subject_id: int | None = None,
        options: dict | None = None,
        db=None,
        progress_callback=None,
        file_path: str | None = None,
        page_images: dict[int, bytes] | None = None,
        # P3-2: resume checkpoint — when set, single-pass skips completed stages
        resume_from_checkpoint: dict | None = None,
    ) -> dict:
        """Execute all pipeline stages in sequence.

        P2-2: when source_type == "pdf" and total_pages > chunk_size, the body
        is split into page-chunks. Each chunk runs the full stage list in
        isolation; a single chunk failure does not abort sibling chunks.
        Single-chunk path retains exact backward compatibility — txt, image
        OCR text, page-range-restricted PDFs, and short PDFs all hit the
        legacy single-pass branch.

        Args:
            file_content: raw file bytes (PDF, txt, etc.) — fallback when no path
            file_path: tmp path on disk; preferred for PDF (mmap, no heap copy).
            source_type: "pdf" | "txt"
            source_file: original filename
            subject: optional subject hint
            options: {"enable_ai_repair": bool, "confidence_threshold": float}
            db: optional AsyncSession for the review stage
            progress_callback: optional async callable(stages_dict, current_stage, errors)
            page_images: pre-rendered page image bytes keyed by 1-based page number.
                         When provided (e.g. from image imports), bypasses
                         _render_page_images so the ocr_correction stage can
                         pass the original image to multimodal models like PaddleOCR-VL.

        Returns:
            Pipeline result dict with status, stats, stages, and errors.
        """
        if file_path is None and file_content is None:
            raise ValueError("either file_path or file_content must be provided")
        opts = options or {}
        if options is not None:
            self.options = opts

        started_at = datetime.now().isoformat()

        # Resolve import mode and strategy (shared across all chunks)
        mode_str = opts.get("import_mode", "auto")
        try:
            import_mode = ImportMode(mode_str)
        except ValueError:
            import_mode = ImportMode.AUTO
        strategy = get_strategy(import_mode)

        # Load watermark rules once (shared across all chunks)
        watermark_patterns: list = []
        if db:
            try:
                from app.services.watermark_service import load_rules
                watermark_patterns = await load_rules(db)
            except Exception as e:
                logger.warning("Failed to load watermark rules from DB, using defaults: %s", e)
        if not watermark_patterns:
            from app.services.watermark_service import get_default_patterns
            watermark_patterns = get_default_patterns()

        shared = {
            "import_mode": import_mode,
            "strategy": strategy,
            "watermark_patterns": watermark_patterns,
        }

        _pipe_logger = logging.getLogger("app.pipeline")
        log_event(
            _pipe_logger, "pipeline.plan.start",
            pipeline_id=self.pipeline_id, source_type=source_type,
            source_file=source_file, import_mode=mode_str,
            ocr_enabled=opts.get("enable_ocr_correction", True),
            enable_ai_repair=opts.get("enable_ai_repair", True),
        )

        # Decide chunked vs single-pass
        chunk_ranges = self._plan_chunks(
            file_content=file_content,
            file_path=file_path,
            source_type=source_type,
            opts=opts,
            db=db,
        )

        # Resolve effective page range for rendering
        render_page_start = opts.get("page_start") or 1
        render_page_end = opts.get("page_end")

        # Pre-render page images once (expensive — reused across chunks)
        # When PDF_RENDER_PAGE_WINDOW > 0, skip pre-render — each chunk
        # renders its own window via iter_pages() in _execute_chunk.
        from app.core.config import settings

        page_window = settings.PDF_RENDER_PAGE_WINDOW
        pre_render = page_window <= 0  # skip pre-render when window is set

        from app.services.pdf_renderer_service import pdf_renderer

        page_images: dict[int, bytes] | None = None
        page_image_refs: dict[int, str] | None = None
        pdf_render_result = None
        if pre_render and source_type == "pdf":
            pdf_render_result = await pdf_renderer.render_pages(
                file_content=file_content,
                file_path=file_path,
                source_type=source_type,
                page_start=render_page_start,
                page_end=render_page_end,
            )
            page_images = pdf_render_result.page_images if pdf_render_result.rendered_count else None
            page_image_refs = pdf_render_result.page_file_refs or None

        log_event(
            _pipe_logger, "pipeline.plan.finish",
            pipeline_id=self.pipeline_id, source_type=source_type,
            source_file=source_file, import_mode=mode_str,
            chunk_count=len(chunk_ranges) if chunk_ranges else 1,
        )

        try:
            if len(chunk_ranges) <= 1:
                result = await self._run_single_pass(
                    file_content=file_content,
                    file_path=file_path,
                    source_type=source_type,
                    source_file=source_file,
                    subject=subject,
                    subject_id=subject_id,
                    opts=opts,
                    db=db,
                    shared=shared,
                    progress_callback=progress_callback,
                    started_at=started_at,
                    page_images=page_images,
                    page_image_refs=page_image_refs,
                    resume_from_checkpoint=resume_from_checkpoint,
                )
            else:
                result = await self._run_chunked(
                    file_content=file_content,
                    file_path=file_path,
                    source_type=source_type,
                    source_file=source_file,
                    subject=subject,
                    subject_id=subject_id,
                    opts=opts,
                    db=db,
                    shared=shared,
                    progress_callback=progress_callback,
                    chunk_ranges=chunk_ranges,
                    started_at=started_at,
                    page_images=page_images,
                    page_image_refs=page_image_refs,
                )
        finally:
            if pdf_render_result is not None:
                await pdf_renderer.cleanup(pdf_render_result)
        return result

    # ------------------------------------------------------------------
    # P2-2 chunk planning + single-pass extraction
    # ------------------------------------------------------------------

    def _plan_chunks(
        self,
        *,
        file_content: bytes | None,
        file_path: str | None,
        source_type: str,
        opts: dict,
        db,
    ) -> list[tuple[int, int]]:
        """Decide how to split this run into page-chunks.

        Args:
            opts: pipeline options — may include page_start/page_end for
                  user-specified range. When set, chunking uses the selected
                  range instead of the whole document.

        Returns:
            [] when chunking is not applicable (txt, no DB, or when the
              selected page range fits in a single chunk). The caller falls
              back to the legacy single-pass branch.
            [(s1, e1), ...] otherwise — 1-based closed page ranges.
        """
        # Chunking only kicks in for PDFs with a DB session (checkpoint needs DB)
        if source_type != "pdf" or db is None:
            return []

        chunk_size = _resolve_chunk_size()
        if chunk_size <= 0:
            return []

        # Resolve effective page range
        effective_start = opts.get("page_start") or 1
        effective_end = opts.get("page_end") or 0  # 0 means "unknown / entire doc"
        has_user_range = effective_end > 0

        try:
            total_pages = _read_pdf_page_count(file_path or file_content)
        except Exception as exc:
            logger.warning("Failed to read PDF page count, falling back to single-pass: %s", exc)
            return []

        if total_pages <= 0:
            return []

        # Determine the actual page count we need to chunk over
        if has_user_range:
            if effective_start > total_pages:
                logger.warning("page_start %d exceeds total_pages %d, cannot chunk", effective_start, total_pages)
                return []
            page_count_for_chunking = min(effective_end, total_pages) - effective_start + 1
        else:
            effective_end = total_pages
            page_count_for_chunking = total_pages

        if page_count_for_chunking <= chunk_size:
            return []  # single chunk = single-pass path

        # Use range-based chunking when page range is specified
        if has_user_range:
            return split_page_range(effective_start, effective_end, chunk_size)

        return _split_into_chunks(total_pages, chunk_size)

    async def _run_single_pass(
        self,
        *,
        file_content: bytes | None,
        file_path: str | None,
        source_type: str,
        source_file: str,
        subject: str | None,
        subject_id: int | None = None,
        opts: dict,
        db,
        shared: dict,
        progress_callback,
        started_at: str,
        page_start: int | None = None,
        page_end: int | None = None,
        chunk_seen_hashes: set | None = None,
        chunk_logical_end: int | None = None,
        page_images: dict[int, bytes] | None = None,
        page_image_refs: dict[int, str] | None = None,
        # P3-2: when set, skip already-completed stages. Only used by
        # resume (single-pass). Chunked mode always passes None.
        resume_from_checkpoint: dict | None = None,
    ) -> dict:
        """Execute every stage once for the given (optionally page-restricted) input.

        This is the legacy run() body extracted verbatim — chunked mode calls
        this once per chunk with page_start/page_end injected.

        P2-3 / P1-3: ``chunk_seen_hashes`` (mutable set across chunks) and
        ``chunk_logical_end`` (this chunk's own last page; pages past it are
        overlap territory) are threaded through ``data`` so ``_run_split`` can
        dedupe overlap-region duplicates and emit the unclosed-boundary
        warning. Both are None for legacy single-pass.

        P3-2: ``resume_from_checkpoint`` — when set, completed stages in the
        checkpoint are skipped. Stage outputs for skipped stages are NOT
        restored from checkpoint (they must be re-derived from the source).
        This saves AI call costs for completed stages but not extraction cost.
        """
        # Each pass gets its own stage instances so per-stage status doesn't
        # leak between chunks.
        self._build_pipeline()

        _sp_logger = logging.getLogger("app.pipeline")
        _sp_start = time.monotonic()
        log_event(
            _sp_logger, "pipeline.single_pass.start",
            pipeline_id=self.pipeline_id, source_type=source_type,
            page_start=page_start, page_end=page_end,
        )

        # When called from the chunk loop, override the page range in opts
        # without mutating the caller's dict.
        if page_start is not None or page_end is not None:
            opts = {**opts, "page_start": page_start, "page_end": page_end}

        # Resolve vision model config for PaddleOCR-VL fallback
        vision_config = None
        if db is not None:
            from app.services.model_config_resolver import resolve_active_model
            try:
                resolved = await resolve_active_model(db, feature="vision")
                if resolved and resolved.get("api_key"):
                    vision_config = resolved
                    logger.info(
                        "Vision model configured: %s (provider=%s)",
                        vision_config.get("display_name") or vision_config.get("model_name", "?"),
                        vision_config.get("provider", "?"),
                    )
            except Exception as exc:
                logger.warning("Failed to resolve vision model config: %s", exc)

        # Accumulated data passed between stages
        data: dict[str, Any] = {
            "file_content": file_content,
            "file_path": file_path,
            "source_type": source_type,
            "source_file": source_file,
            "subject": subject,
            "subject_id": subject_id,
            "options": opts,
            "db": db,
            "vision_config": vision_config,
            "import_mode": shared["import_mode"],
            "strategy": shared["strategy"],
            "watermark_patterns": shared["watermark_patterns"],
            "page_images": page_images,
            "page_image_refs": page_image_refs,
            "raw_blocks": [],
            "normalized_blocks": [],
            "layout_result": {},
            "split_mode": "standard",
            "frozen_option_registry": {},
            "frozen_structures": [],
            "freeze_checksum": "",
            "freeze_mode": "legacy",
            "freeze_ir_warnings": [],
            "freeze_dual_diagnostics": {},
            "frozen_option_registry_ir": {},
            "quality_gate_shadow_records": [],
            "cross_page_links": [],
            "raw_questions": [],
            "matched": [],
            "unmatched": [],
            "questions": [],
        }
        # P2-4: chunked 路径在 shared 里挂了 hash_index 实例，透传给
        # similarity_match stage；单 pass 时 shared 没有该 key，stage
        # 默认 hash_index=None 会走旧的 difflib fallback。
        if shared.get("hash_index") is not None:
            data["hash_index"] = shared["hash_index"]
        # P2-3 / P1-3 chunk overlap state — only populated in chunked mode
        if chunk_seen_hashes is not None:
            data["_chunk_seen_hashes"] = chunk_seen_hashes
        if chunk_logical_end is not None:
            data["_chunk_logical_end"] = chunk_logical_end

        pipeline_errors: list[str] = []
        overall_status = "completed"

        # P3-2: per-stage checkpoint tracking — only used in single-pass mode.
        # Chunked mode has its own checkpoint via pipeline_checkpoint.py.
        _is_chunked_mode = chunk_seen_hashes is not None
        completed_stages: list[str] = []
        has_resume_ckpt = resume_from_checkpoint is not None
        if has_resume_ckpt:
            completed_stages = list(resume_from_checkpoint.get("completed_stages") or [])
            logger.info(
                "Resuming pipeline %s from checkpoint: %d stages completed",
                self.pipeline_id, len(completed_stages),
            )

        # Write initial checkpoint so we have metadata even if first stage fails
        if not _is_chunked_mode:
            await _write_stage_checkpoint(
                self.pipeline_id,
                completed_stages=list(completed_stages),
                current_stage="",
                stage_statuses={},
                source_type=source_type,
                source_file=source_file,
                subject=subject,
                options=opts,
            )

        # P4-3: try restoring stage outputs from artifacts
        _artifact_skipped: set[str] = set()
        if has_resume_ckpt:
            restored_stage, _artifact_skipped = _restore_from_artifacts(
                self.pipeline_id, completed_stages, data,
            )
            if restored_stage:
                logger.info(
                    "True resume from artifact: restored=%s skipped_stages=%s",
                    restored_stage, sorted(_artifact_skipped),
                )

        for name, stage in self.stages.items():

            # P4-3: skip stages restored from artifacts
            if name in _artifact_skipped:
                logger.info("Skipping stage '%s' (restored from artifact)", name)
                stage.status = "completed"
                stage.duration_ms = 0
                if name not in completed_stages:
                    completed_stages.append(name)
                continue

            # P5-3: skip review if pipeline already failed (prevent partial
            # data leaking into review pool when a prior stage failed but
            # execution continued past the break-only-for-extract/normalize gate)
            if name == "review" and overall_status == "failed":
                logger.warning(
                    "Skipping 'review' stage: pipeline already failed at "
                    "prior stage (errors=%s)",
                    pipeline_errors,
                )
                stage.status = "skipped"
                stage.duration_ms = 0
                continue

            if progress_callback:
                try:
                    await progress_callback(
                        {n: s.to_dict() for n, s in self.stages.items()},
                        name,
                        pipeline_errors,
                    )
                except Exception:
                    pass

            try:
                result = await stage.run_async(**data)
                if isinstance(result, dict):
                    if result.get("warnings"):
                        stage.warnings.extend(result["warnings"])
                    data.update(result)
                    # 隐患① 修复：每次 stage 写入 normalized_blocks 都同步更新
                    # count，确保即便后续 stage 在 match 之前失败，stats 仍能
                    # 反映真实的 block 数（之前只在 match 后缓存，前序失败会
                    # 静默归零）。
                    if "normalized_blocks" in result:
                        data["normalized_block_count"] = len(result["normalized_blocks"])
                # P6-2: update per-stage profiling metrics from data & result
                _update_stage_metrics(stage, data, result)
                # P0-1 / P1-A: 大字段一过最后消费者立即释放，避免随 8+ 个阶段
                # 一起驻留内存。400 页扫描 PDF 下，OCR 后的 normalized_blocks
                # 单独可达 50~200 MB（含 boxes），是仅次于 PDF 字节的大头。
                if name == "extract":
                    # PDF/图片字节保留给 ocr_correction（PaddleOCR-VL 需要原始图像）
                    pass
                elif name == "normalize_text":
                    # raw_blocks 已并入 normalized_blocks，无后续消费者
                    data.pop("raw_blocks", None)
                elif name == "ocr_correction":
                    # OCR correction stage finished, release original bytes
                    # and rendered page images (PaddleOCR-VL was last consumer).
                    # Keep file_path for potential VL_REBUILD in split stage.
                    data.pop("file_content", None)
                    data.pop("page_images", None)
                elif name == "split":
                    # split 后释放 file_path（VL_REBUILD 不再需要）
                    data.pop("file_path", None)
                    # ── 观察：split 质量评估 ──
                    try:
                        from app.evaluation.split_quality import evaluate_split_quality
                        sq = evaluate_split_quality(
                            result.get("raw_questions", []),
                            result.get("split_diagnostics"),
                            data.get("layout_result"),
                        )
                        data["split_quality"] = sq
                    except Exception as exc:
                        logger.warning("split_quality evaluation failed: %s", exc)
                    # ── 观察：per-run routing metrics ──
                    try:
                        from app.evaluation.routing_metrics import build_routing_metrics
                        data["routing_metrics"] = build_routing_metrics(data)
                    except Exception as exc:
                        logger.warning("routing_metrics build failed: %s", exc)
                elif name == "match":
                    # match 后无人再读 normalized_blocks，count 已在写入时缓存
                    data.pop("normalized_blocks", None)
                elif name == "normalize_schema":
                    # questions 已落地，原始题目/匹配结果不再被读取
                    data.pop("raw_questions", None)
                    data.pop("matched", None)
                    data.pop("unmatched", None)

                # P3-2: write checkpoint after each completed stage (single-pass only)
                if not _is_chunked_mode:
                    completed_stages.append(name)
                    await _write_stage_checkpoint(
                        self.pipeline_id,
                        completed_stages=list(completed_stages),
                        current_stage=name,
                        stage_statuses={n: s.to_dict() for n, s in self.stages.items()},
                        source_type=source_type,
                        source_file=source_file,
                        subject=subject,
                        options=opts,
                    )
                    # P4-3: save artifact for resumable stages
                    _save_stage_artifact(self.pipeline_id, name, data)
            except Exception:
                overall_status = "failed"
                pipeline_errors.append(f"stage '{name}' failed: {stage.error}")
                # P3-2: write failure checkpoint (single-pass only)
                if not _is_chunked_mode:
                    await _write_stage_checkpoint(
                        self.pipeline_id,
                        completed_stages=list(completed_stages),
                        current_stage=name,
                        stage_statuses={n: s.to_dict() for n, s in self.stages.items()},
                        failed_stage=name,
                        error=stage.error,
                        source_type=source_type,
                        source_file=source_file,
                        subject=subject,
                        options=opts,
                    )
                if name in ("extract", "normalize_text", "ocr_correction"):
                    # 失败路径同样释放
                    data.pop("file_content", None)
                    data.pop("file_path", None)
                    data.pop("page_images", None)
                    if name in ("extract", "normalize_text"):
                        break
                logger.warning("Stage '%s' failed, continuing with partial results", name)

            if progress_callback:
                try:
                    await progress_callback(
                        {n: s.to_dict() for n, s in self.stages.items()},
                        name,
                        pipeline_errors,
                    )
                except Exception:
                    pass

        # P3-2: clear checkpoint on successful completion (single-pass only)
        if not _is_chunked_mode and overall_status == "completed":
            await _clear_stage_checkpoint(self.pipeline_id)
            _save_completed_marker(self.pipeline_id)

        # P4-3: write failed marker for TTL-based artifact cleanup
        if not _is_chunked_mode and overall_status == "failed":
            _save_failed_marker(self.pipeline_id)

        stats = _build_stats(data, self.stages)
        diagnostics = _build_diagnostics(data, self.stages)
        finished_at = datetime.now().isoformat()

        # P4-5: quality report from existing data
        quality_report = _build_quality_report(data, diagnostics)
        # P6-2: attach performance summary to quality report
        perf_profile = diagnostics.get("performance_profile", {})
        if perf_profile and "_summary" in perf_profile:
            quality_report["performance_summary"] = perf_profile["_summary"]
        # ── 观察：routing metrics → quality report ──
        routing_metrics = data.get("routing_metrics")
        if routing_metrics:
            quality_report["routing_metrics"] = routing_metrics
        split_quality = data.get("split_quality")
        if split_quality:
            quality_report["split_quality_evaluation"] = split_quality

        # ── 生产稳定性日志：每次 pipeline 完成记录 routing 决策 ──
        if routing_metrics:
            _log_routing_stability(self.pipeline_id, routing_metrics, split_quality)
        # P4-2: artifact list for resume diagnostics
        artifacts_list = _list_artifacts(self.pipeline_id)

        log_event(
            _sp_logger, "pipeline.single_pass.finish",
            pipeline_id=self.pipeline_id, source_type=source_type,
            page_start=page_start, page_end=page_end,
            status=overall_status,
            duration_ms=round((time.monotonic() - _sp_start) * 1000),
            question_count=data.get("stats", {}).get("to_review", 0) if isinstance(data.get("stats"), dict) else 0,
        )

        return {
            "pipeline_id": self.pipeline_id,
            "status": overall_status,
            "batch_id": data.get("batch_id", ""),
            "stats": stats,
            "diagnostics": diagnostics,
            "quality_report": quality_report,
            "artifacts": artifacts_list,
            "stages": {name: s.to_dict() for name, s in self.stages.items()},
            "errors": pipeline_errors,
            "started_at": started_at,
            "finished_at": finished_at,
            # P2-4: chunked 路径需要拿到本 chunk 已写入的 hash 推到
            # GlobalHashIndex；single-pass 调用方忽略即可。
            "review_new_hashes": data.get("review_new_hashes") or [],
        }

    async def _execute_chunk(
        self,
        *,
        chunk_index: int,
        page_start: int,
        logical_end: int,
        total_pages: int,
        is_last_chunk: bool,
        chunk_overlap: int,
        file_content: bytes | None,
        file_path: str | None,
        source_type: str,
        source_file: str,
        subject: str | None,
        subject_id: int | None = None,
        opts: dict,
        db,
        shared: dict,
        progress_callback,
        started_at: str,
        seen_hashes: set,
        hash_index,
        page_images: dict[int, bytes] | None = None,
        page_image_refs: dict[int, str] | None = None,
    ) -> dict:
        """Run one chunk end-to-end with checkpoint writes + failure isolation.

        Shared by ``_run_chunked`` (initial import) and
        ``resume_pipeline_background`` (P2-5 manual resume) so the chunk-level
        contract — mark_running → run_single_pass → update_status →
        push hashes → return outcome dict — stays in one place.

        The returned dict matches the per-chunk diagnostics shape consumed by
        ``diagnostics.chunks`` in the pipeline-level result.
        """
        from app.core.config import settings
        from app.services.pdf_renderer_service import pdf_renderer

        # When PDF_RENDER_PAGE_WINDOW > 0, render only this chunk's pages
        # using iter_pages() streaming — avoids holding all pages in memory.
        page_window = settings.PDF_RENDER_PAGE_WINDOW
        if page_window > 0 and source_type == "pdf" and page_images is None:
            chunk_page_images: dict[int, bytes] = {}
            async for page_num, png_bytes in pdf_renderer.iter_pages(
                file_content=file_content,
                file_path=file_path,
                source_type=source_type,
                page_start=page_start,
                page_end=logical_end,
            ):
                chunk_page_images[page_num] = png_bytes
            if chunk_page_images:
                page_images = chunk_page_images

        await ckpt.mark_chunk_running(db, self.pipeline_id, chunk_index)
        from app.features import pipeline_checkpoint as ckpt
        await ckpt.invalidate_progress_cache(self.pipeline_id)

        _chunk_logger = logging.getLogger("app.pipeline")
        _chunk_start = time.monotonic()
        bind_log_context(chunk_index=chunk_index)
        log_event(
            _chunk_logger, "pipeline.chunk.start",
            pipeline_id=self.pipeline_id,
            chunk_index=chunk_index,
            page_start=page_start,
            page_end=logical_end,
        )

        # P2-3: extend page_end by overlap so the splitter can finish the
        # last question whose tail crosses the chunk boundary. Cap at
        # total_pages so we never read past the document. The final chunk
        # has no overlap (nothing comes after it).
        effective_end = (
            logical_end
            if is_last_chunk
            else min(logical_end + chunk_overlap, total_pages)
        )

        chunk_status = "completed"
        chunk_error: str | None = None
        chunk_result: dict = {}
        try:
            chunk_result = await self._run_single_pass(
                file_content=file_content,
                file_path=file_path,
                source_type=source_type,
                source_file=source_file,
                subject=subject,
                subject_id=subject_id,
                opts=opts,
                db=db,
                shared=shared,
                progress_callback=progress_callback,
                started_at=started_at,
                page_start=page_start,
                page_end=effective_end,
                chunk_seen_hashes=seen_hashes,
                chunk_logical_end=logical_end,
                page_images=page_images,
                page_image_refs=page_image_refs,
            )
            if chunk_result.get("status") != "completed":
                chunk_status = "failed"
                errs = chunk_result.get("errors") or []
                chunk_error = errs[0] if errs else "chunk failed without explicit error"
        except Exception as exc:
            # _run_single_pass should swallow stage errors itself, but if
            # something escapes (e.g. extract crash before stage loop) we
            # must still keep the import alive.
            logger.exception(
                "chunk %d (pages %d-%d) raised unexpectedly",
                chunk_index, page_start, logical_end,
            )
            chunk_status = "failed"
            chunk_error = f"{type(exc).__name__}: {exc}"
            chunk_result = {"errors": [chunk_error]}

        written = (chunk_result.get("stats") or {}).get("to_review", 0)
        batch_id = chunk_result.get("batch_id") or None

        # P2-4: push (subject, hash, import_id) so subsequent chunks can hit
        # this chunk's writes via similarity_match. add_import is a no-op when
        # the index ran into the SQL fallback.
        if hash_index is not None and chunk_status == "completed":
            for subj, qhash, iid in chunk_result.get("review_new_hashes") or []:
                hash_index.add_import(subj, qhash, iid)

        await ckpt.update_chunk_status(
            db,
            self.pipeline_id,
            chunk_index,
            status=chunk_status,
            batch_id=batch_id,
            question_count=written,
            error_message=chunk_error,
        )
        await ckpt.invalidate_progress_cache(self.pipeline_id)

        _chunk_event = "pipeline.chunk.finish" if chunk_status == "completed" else "pipeline.chunk.error"
        _chunk_level = "info" if chunk_status == "completed" else "error"
        log_event(
            _chunk_logger, _chunk_event,
            level=_chunk_level,
            pipeline_id=self.pipeline_id,
            chunk_index=chunk_index,
            page_start=page_start,
            page_end=logical_end,
            effective_page_end=effective_end,
            status=chunk_status,
            duration_ms=round((time.monotonic() - _chunk_start) * 1000),
            batch_id=batch_id or "-",
            question_count=written,
            error_message=(chunk_error or "")[:300],
        )

        return {
            "chunk_index": chunk_index,
            "page_start": page_start,
            "page_end": logical_end,
            "effective_page_end": effective_end,
            "status": chunk_status,
            "batch_id": batch_id,
            "question_count": written,
            "error_message": chunk_error,
            "diagnostics": _slim_chunk_diagnostics(chunk_result.get("diagnostics") or {}),
            "stages": chunk_result.get("stages") or {},
        }

    async def _run_chunked(
        self,
        *,
        file_content: bytes | None,
        file_path: str | None,
        source_type: str,
        source_file: str,
        subject: str | None,
        subject_id: int | None = None,
        opts: dict,
        db,
        shared: dict,
        progress_callback,
        chunk_ranges: list[tuple[int, int]],
        started_at: str,
        page_images: dict[int, bytes] | None = None,
        page_image_refs: dict[int, str] | None = None,
    ) -> dict:
        """Drive a multi-chunk run with checkpoint persistence and failure isolation.

        For each (page_start, page_end):
            1. mark_chunk_running → run all stages → update_chunk_status
            2. On chunk-level exception (after the catch in _run_single_pass)
               or stage_status == "failed", record error_message and continue
               to the next chunk — never raise out of this method.

        P0-3: 每个 chunk 在自己的 ``AsyncSession`` 上下文里跑，事务边界 =
        chunk 边界。整段循环不再共享单个 session，避免 PG
        ``idle_in_transaction_session_timeout`` 在长 chunked 导入中触发。
        初始化（create_pipeline_record / create_chunk_records / hash_index
        load）也分别用临时 session，跑完即释放连接。

        Pipeline-level status:
            - "completed" iff all chunks completed AND none recorded errors
            - "paused" otherwise (manual resume via P2-5)
        """
        from app.features import pipeline_checkpoint as ckpt
        from app.features.global_hash_index import GlobalHashIndex

        total_pages = chunk_ranges[-1][1]
        chunk_size = _resolve_chunk_size()
        chunk_overlap = _resolve_chunk_overlap()

        # P0-3: 从调用方传入的 db 推导 sessionmaker，生产路径等价于全局
        # async_session；测试路径绑到 tmp_path engine，避免污染全局。
        session_factory = _derive_session_factory(db)

        # P0-3: 把首次实际生效的 watermark patterns 序列化后落库，resume
        # 时直接复用，避免规则漂移。
        watermark_snapshot = _serialize_watermark_patterns(
            shared.get("watermark_patterns") or []
        )

        # Create parent + chunk records up-front (DB authoritative).
        # 每个初始化步骤用独立临时 session，避免长事务。
        async with session_factory() as init_db:
            await ckpt.create_pipeline_record(
                init_db,
                pipeline_id=self.pipeline_id,
                source_type=source_type,
                source_file=source_file or None,
                total_pages=total_pages,
                chunk_size=chunk_size,
                created_by=self.created_by,
                source_sha256=self.source_sha256,
                watermark_snapshot=watermark_snapshot or None,
            )
            await ckpt.create_chunk_records(init_db, self.pipeline_id, chunk_ranges)

        # P2-4: chunked 路径只构造一次 hash 索引，整个 pipeline 共用。失败
        # 不阻断主流程——index_loaded=False 时 similarity_match 退化为
        # subject 全表扫描（旧行为），仅打 warning。
        hash_index: GlobalHashIndex | None = GlobalHashIndex()
        try:
            async with session_factory() as init_db:
                await hash_index.load(init_db)
        except Exception:
            logger.exception("GlobalHashIndex.load failed; chunked similarity match will fallback")
            hash_index = None
        if hash_index is not None:
            shared = {**shared, "hash_index": hash_index}

        chunk_results: list[dict] = []
        pipeline_errors: list[str] = []
        any_chunk_failed = False
        # P2-3 / P1-3: shared across all chunks so dedup sees what siblings already wrote
        seen_hashes: set[str] = set()

        _chunked_logger = logging.getLogger("app.pipeline")
        _chunked_start = time.monotonic()
        log_event(
            _chunked_logger, "pipeline.chunked.start",
            pipeline_id=self.pipeline_id,
            total_pages=total_pages,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            total_chunks=len(chunk_ranges),
        )

        try:
            for chunk_index, (page_start, logical_end) in enumerate(chunk_ranges):
                is_last_chunk = chunk_index == len(chunk_ranges) - 1
                # P0-3: 每个 chunk 一个独立 session（事务边界 = chunk 边界）。
                async with session_factory() as chunk_db:
                    outcome = await self._execute_chunk(
                        chunk_index=chunk_index,
                        page_start=page_start,
                        logical_end=logical_end,
                        total_pages=total_pages,
                        is_last_chunk=is_last_chunk,
                        chunk_overlap=chunk_overlap,
                        file_content=file_content,
                        file_path=file_path,
                        source_type=source_type,
                        source_file=source_file,
                        subject=subject,
                        subject_id=subject_id,
                        opts=opts,
                        db=chunk_db,
                        shared=shared,
                        progress_callback=progress_callback,
                        started_at=started_at,
                        seen_hashes=seen_hashes,
                        hash_index=hash_index,
                        page_images=page_images,
                        page_image_refs=page_image_refs,
                    )
                chunk_results.append(outcome)
                if outcome["status"] == "failed":
                    any_chunk_failed = True
                    pipeline_errors.append(
                        f"chunk {chunk_index} (pages {page_start}-{logical_end}) "
                        f"failed: {outcome['error_message']}"
                    )
        finally:
            # P1-1: 清空 hash_index 内部 dict，避免 chunk 异常路径下大字典
            # （最坏 ~50 万条 question + N 条 import）残留在 GlobalHashIndex
            # 实例上。低配 2C2G 服务器友好。
            if hash_index is not None:
                hash_index._question_index.clear()
                hash_index._import_index.clear()

        overall_status = "paused" if any_chunk_failed else "completed"
        async with session_factory() as final_db:
            await ckpt.update_pipeline_status(
                final_db,
                self.pipeline_id,
                status=overall_status,
                error_message=pipeline_errors[0] if pipeline_errors else None,
                finished=True,
            )
        await ckpt.invalidate_progress_cache(self.pipeline_id)

        # Aggregate stats across chunks
        agg_stats = {
            "total_chunks": len(chunk_ranges),
            "completed_chunks": sum(1 for c in chunk_results if c["status"] == "completed"),
            "failed_chunks": sum(1 for c in chunk_results if c["status"] == "failed"),
            "to_review": sum(c["question_count"] or 0 for c in chunk_results),
            "extracted": total_pages,
            "total": total_pages,
        }

        risk_flag_counts = _merge_risk_flag_counts(chunk_results)

        finished_at = datetime.now().isoformat()
        # Pick a representative batch_id for the overall pipeline (first
        # successful chunk's batch). Each chunk has its own batch_id under
        # the hood; resume logic uses chunk-level records, not this field.
        first_batch_id = next(
            (c["batch_id"] for c in chunk_results if c["batch_id"]),
            "",
        )

        _chunked_event = "pipeline.chunked.finish" if overall_status == "completed" else "pipeline.chunked.paused"
        _chunked_level = "info" if overall_status == "completed" else "warning"
        log_event(
            _chunked_logger, _chunked_event,
            level=_chunked_level,
            pipeline_id=self.pipeline_id,
            total_pages=total_pages,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            total_chunks=len(chunk_ranges),
            completed_chunks=agg_stats["completed_chunks"],
            failed_chunks=agg_stats["failed_chunks"],
            status=overall_status,
            duration_ms=round((time.monotonic() - _chunked_start) * 1000),
        )

        return {
            "pipeline_id": self.pipeline_id,
            "status": overall_status,
            "batch_id": first_batch_id,
            "stats": agg_stats,
            "diagnostics": {
                "chunked": True,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "total_pages": total_pages,
                "risk_flag_counts": risk_flag_counts,
                "chunks": chunk_results,
                "hash_index": (
                    dict(hash_index.stats) if hash_index is not None else None
                ),
            },
            "stages": {},  # per-chunk stage info lives in diagnostics.chunks
            "errors": pipeline_errors,
            "started_at": started_at,
            "finished_at": finished_at,
        }


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


async def run_import_pipeline(
    file_content: bytes | None = None,
    source_type: str = "pdf",
    source_file: str = "",
    subject: str | None = None,
    subject_id: int | None = None,
    options: dict | None = None,
    db=None,
    progress_callback=None,
    pipeline_id: str | None = None,
    file_path: str | None = None,
    created_by: str | None = None,
    source_sha256: str | None = None,
    page_images: dict[int, bytes] | None = None,
    # P3-2: resume checkpoint for single-pass resume
    resume_from_checkpoint: dict | None = None,
) -> dict:
    """完整的导入流水线入口。

    串联 Stage 1 (文本清洗) → Stage 3 (题目切分) → Stage 4 (答案匹配)
    → Stage 5 (题目标准化) → Stage 6 (AI 修复, 可选) → Stage 7 (审核入库).

    Args:
        file_content: 文件原始字节（无 file_path 时使用）
        file_path: 已落盘的临时文件路径（PDF 优先走此分支以走 mmap）
        source_type: "pdf" | "txt" | "image"
        source_file: 原始文件名
        subject: 科目提示（可选）
        options: {"enable_ai_repair": bool, "confidence_threshold": float}
        db: 异步数据库会话（review 阶段需要）
        page_images: 预渲染的页面图片字典（{1: image_bytes}），传入后管线跳过
                     _render_page_images，直接使用。用于图片导入场景，让多模态
                     OCR 纠错模型（如 PaddleOCR-VL）能看到原始图片。
        resume_from_checkpoint: P3-2 resume checkpoint data. When set, the
                     pipeline re-runs from extract but uses the same pipeline_id
                     for status continuity.

    Returns:
        Pipeline result dict.
    """
    if file_path is None and file_content is None:
        raise ValueError("either file_path or file_content must be provided")

    if not pipeline_id:
        pipeline_id = f"pl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    # Auto-detect Wangdao preset from filename
    opts = dict(options) if options else {}
    if "enable_wangdao_preprocess" not in opts:
        lower_name = (source_file or "").lower()
        if "王道" in (source_file or "") or "wangdao" in lower_name or re.search(r"(?:^|[_\-\s])408(?:[_\-\s.]|$)", lower_name):
            opts["enable_wangdao_preprocess"] = True

    # EXAM mode disables wangdao preprocessing by default
    mode_str = opts.get("import_mode", "auto")
    try:
        import_mode = ImportMode(mode_str)
    except ValueError:
        import_mode = ImportMode.AUTO
    if import_mode == ImportMode.EXAM and "enable_wangdao_preprocess" not in (options or {}):
        opts["enable_wangdao_preprocess"] = False

    pipeline = ImportPipeline(options=opts)
    pipeline.pipeline_id = pipeline_id
    pipeline.created_by = created_by
    pipeline.source_sha256 = source_sha256

    _pipe_logger = logging.getLogger("app.pipeline")
    _run_start = time.monotonic()
    bind_log_context(pipeline_id=pipeline_id, source_type=source_type, source_file=source_file)

    log_event(
        _pipe_logger, "pipeline.run.start",
        pipeline_id=pipeline_id, source_type=source_type,
        source_file=source_file, subject=subject or "-",
    )

    try:
        result = await pipeline.run(
            file_content=file_content,
            file_path=file_path,
            source_type=source_type,
            source_file=source_file,
            subject=subject,
            subject_id=subject_id,
            options=opts,
            db=db,
            progress_callback=progress_callback,
            page_images=page_images,
            resume_from_checkpoint=resume_from_checkpoint,
        )
        result["pipeline_id"] = pipeline_id

        log_event(
            _pipe_logger, "pipeline.run.finish",
            pipeline_id=pipeline_id, source_type=source_type,
            source_file=source_file,
            status=result.get("status", "unknown"),
            duration_ms=round((time.monotonic() - _run_start) * 1000),
        )
        return result
    except Exception as exc:
        log_event(
            _pipe_logger, "pipeline.run.error",
            level="error",
            pipeline_id=pipeline_id, source_type=source_type,
            source_file=source_file,
            duration_ms=round((time.monotonic() - _run_start) * 1000),
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
        )
        raise


async def run_pipeline_background(
    pipeline_id: str,
    source_type: str,
    source_file: str,
    file_content: bytes | None = None,
    file_path: str | None = None,
    subject: str | None = None,
    subject_id: int | None = None,
    options: dict | None = None,
    db=None,
    created_by: str | None = None,
    source_sha256: str | None = None,
) -> None:
    """后台运行流水线，结果写入 Redis + 内存。

    P0-1: file_path 优先（API 入口已落盘 tmp 文件），底层 fitz 走 mmap，
    避免 100~400 MB 的 PDF 字节驻留内存。
    """
    if file_path is None and file_content is None:
        raise ValueError("either file_path or file_content must be provided")

    started_at = datetime.now().isoformat()
    # Preserve page_range from the initial store (set by start_import_pipeline)
    # so it survives the background-task store overwrite.
    initial_page_range = _pipeline_store.get(pipeline_id, {}).get("page_range")
    await _set_pipeline_store(pipeline_id, {
        "pipeline_id": pipeline_id,
        "status": "processing",
        "source_type": source_type,
        "current_stage": "extract",
        "stages": {},
        "stats": {},
        "errors": [],
        "started_at": started_at,
        "page_range": initial_page_range,
    })

    async def _progress(stages_dict, current_stage, errors):
        existing = _pipeline_store.get(pipeline_id, {})
        await _set_pipeline_store(pipeline_id, {
            "pipeline_id": pipeline_id,
            "status": "processing",
            "source_type": source_type,
            "current_stage": current_stage,
            "stages": stages_dict,
            "stats": {},
            "errors": errors,
            "started_at": started_at,
            "page_range": existing.get("page_range") or initial_page_range,
        })

    try:
        result = await run_import_pipeline(
            file_content=file_content,
            file_path=file_path,
            source_type=source_type,
            source_file=source_file,
            subject=subject,
            subject_id=subject_id,
            options=options,
            db=db,
            progress_callback=_progress,
            pipeline_id=pipeline_id,
            created_by=created_by,
            source_sha256=source_sha256,
        )
        result["pipeline_id"] = pipeline_id
        # Preserve page_range through the final store write (the pipeline
        # result itself doesn't carry PdfPageRangeInfo — only the upload
        # response does).
        if initial_page_range and "page_range" not in result:
            result["page_range"] = initial_page_range
        await _set_pipeline_store(pipeline_id, result)

        # P7-2: evaluate alert rules against pipeline output
        try:
            alerts = _evaluate_alerts(
                quality_report=result.get("quality_report"),
                diagnostics=result.get("diagnostics"),
            )
            if alerts:
                result["alerts"] = alerts
                await _set_pipeline_store(pipeline_id, result)
        except Exception as alert_exc:
            logger.warning("Alert evaluation failed for pipeline %s: %s", pipeline_id, alert_exc)

        # P7-4: persist quality_report + alerts to DB so they survive restarts
        if db is not None:
            try:
                qr = result.get("quality_report")
                al = result.get("alerts")
                if qr or al:
                    from app.models.import_pipeline import ImportPipeline as ImportPipelineRow
                    from sqlalchemy import update
                    await db.execute(
                        update(ImportPipelineRow)
                        .where(ImportPipelineRow.pipeline_id == pipeline_id)
                        .values(
                            quality_report=qr if qr else None,
                            alerts=al if al else None,
                        )
                    )
                    await db.commit()
            except Exception as persist_exc:
                logger.warning(
                    "Failed to persist quality_report/alerts for pipeline %s: %s",
                    pipeline_id, persist_exc,
                )
    except Exception as exc:
        logger.exception("Pipeline %s failed", pipeline_id)
        existing = _pipeline_store.get(pipeline_id, {})
        await _set_pipeline_store(pipeline_id, {
            "pipeline_id": pipeline_id,
            "status": "failed",
            "source_type": source_type,
            "errors": [str(exc)],
            "started_at": existing.get("started_at", ""),
            "finished_at": datetime.now().isoformat(),
            "page_range": existing.get("page_range"),
        })


async def _load_seen_hashes_for_resume(db, pipeline_id: str) -> set[str]:
    """Rebuild ``seen_hashes`` from already-imported question rows.

    P1-3: 把"以题号为 key"换成"以 ``question_hash`` 为 key"——这一字段在
    ``QuestionImport`` 表已存在（review_service 写入时计算），因此 resume
    路径直接读列就行，不再依赖 ``raw_data["number"]`` 这种易漂移字段。

    P2-3 keeps a function-level set across chunks so the overlap-region dedup
    never re-imports something a sibling chunk already wrote. After a process
    restart that set is gone — without rebuilding it, a resumed chunk could
    drop legitimate questions whose hashes were written earlier. Best-effort:
    rows missing ``question_hash`` are silently skipped.
    """
    from sqlalchemy import select

    from app.models.import_pipeline import ImportPipelineChunk
    from app.models.question_import import QuestionImport

    chunk_subq = (
        select(ImportPipelineChunk.batch_id)
        .where(
            ImportPipelineChunk.pipeline_id == pipeline_id,
            ImportPipelineChunk.status == "completed",
            ImportPipelineChunk.batch_id.isnot(None),
        )
        .scalar_subquery()
    )
    rows = await db.execute(
        select(QuestionImport.question_hash).where(
            QuestionImport.batch_id.in_(chunk_subq),
            QuestionImport.question_hash.isnot(None),
        )
    )
    hashes: set[str] = set()
    for (qhash,) in rows.all():
        if isinstance(qhash, str) and qhash:
            hashes.add(qhash)
    return hashes


async def resume_pipeline_background(
    *,
    pipeline_id: str,
    file_path: str,
    subject: str | None = None,
    subject_id: int | None = None,
    options: dict | None = None,
    db,
) -> None:
    """P2-5: replay only the failed/pending chunks of an existing pipeline.

    Caller (api.v1.imports.resume_pipeline) is responsible for persisting the
    re-uploaded PDF to ``file_path`` and unlinking it once this coroutine
    finishes.

    Behaviour:
        - Loads chunk rows from DB; if no failed/pending chunks remain, marks
          the pipeline ``completed`` and returns immediately.
        - Rebuilds the cross-chunk state (watermark patterns, GlobalHashIndex
          containing already-completed chunk batches, seen_hashes set) so the
          replayed chunks behave the same as if they had run alongside their
          successful siblings.
        - Reuses ``_execute_chunk`` so checkpoint writes, error isolation, and
          hash-index updates stay identical to ``_run_chunked``.
        - Final pipeline status is ``completed`` iff every replayed chunk
          succeeds AND no chunk row remains failed; otherwise stays ``paused``
          so the user can resume again.

    P0-3:
        - 每个 chunk 在独立 ``AsyncSession`` 里跑（事务边界 = chunk 边界），
          避免 PG idle_in_transaction_session_timeout 在长导入中触发。
        - 优先复用 ``pipeline_row.watermark_snapshot``——若存在则跳过
          watermark service 的实时加载，避免管理员在 paused 与 resume
          之间调整规则导致 hash 漂移。NULL（历史 paused pipeline）仍
          fallback 到旧路径。
    """
    from app.features import pipeline_checkpoint as ckpt
    from app.features.global_hash_index import GlobalHashIndex
    from app.models.import_pipeline import (
        ImportPipeline as ImportPipelineRow,
        ImportPipelineChunk,
    )
    from sqlalchemy import select

    opts = dict(options) if options else {}

    # P0-3: 推导 sessionmaker，后续每个 chunk 用独立 session。
    session_factory = _derive_session_factory(db)

    pipeline_row = (
        await db.execute(
            select(ImportPipelineRow).where(
                ImportPipelineRow.pipeline_id == pipeline_id
            )
        )
    ).scalar_one_or_none()
    if pipeline_row is None:
        logger.warning("resume_pipeline_background: pipeline %s missing, abort", pipeline_id)
        return

    # Recover subject_id from checkpoint if caller didn't pass it
    if subject_id is None:
        try:
            ckpt_data = await ckpt.get_stage_checkpoint(pipeline_id)
            if ckpt_data:
                subject_id = ckpt_data.get("subject_id")
                if not subject and ckpt_data.get("subject"):
                    subject = ckpt_data["subject"]
        except Exception:
            logger.debug("resume: could not read checkpoint for subject_id recovery")

    pending = await ckpt.get_pending_chunks(db, pipeline_id)
    if not pending:
        # nothing to do — caller probably hit a race; mark completed if no
        # chunks are still failing.
        await ckpt.update_pipeline_status(
            db, pipeline_id, status="completed", finished=True,
        )
        await ckpt.invalidate_progress_cache(pipeline_id)
        return

    # All chunks (for total count + completed batch_ids), single query.
    all_chunks = (
        (
            await db.execute(
                select(ImportPipelineChunk)
                .where(ImportPipelineChunk.pipeline_id == pipeline_id)
                .order_by(ImportPipelineChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    if not all_chunks:
        logger.warning("resume_pipeline_background: pipeline %s has no chunk rows", pipeline_id)
        return

    total_pages = pipeline_row.total_pages or all_chunks[-1].page_end
    chunk_overlap = _resolve_chunk_overlap()
    max_chunk_index = all_chunks[-1].chunk_index
    completed_batch_ids = [
        c.batch_id for c in all_chunks if c.status == "completed" and c.batch_id
    ]
    # P0-3: snapshot 字段在 ORM 行里就是 list/dict/None；提早抓住后续不再
    # 依赖 pipeline_row 的 detached 状态。
    snapshot = pipeline_row.watermark_snapshot

    # Resolve import mode + strategy + watermark patterns the same way
    # ImportPipeline.run() does, so resumed chunks see the same shared context.
    mode_str = opts.get("import_mode", "auto")
    try:
        import_mode = ImportMode(mode_str)
    except ValueError:
        import_mode = ImportMode.AUTO
    strategy = get_strategy(import_mode)

    # P0-3: 优先用首次导入时的 watermark snapshot；NULL 才回退到实时加载。
    watermark_patterns: list = []
    if snapshot:
        watermark_patterns = _deserialize_watermark_patterns(snapshot)
        if not watermark_patterns:
            logger.warning(
                "resume: watermark_snapshot present but empty/unparsable for %s; "
                "falling back to live rules",
                pipeline_id,
            )
    if not watermark_patterns:
        if not snapshot:
            logger.warning(
                "resume: legacy pipeline %s without watermark_snapshot, "
                "reloading from current rules",
                pipeline_id,
            )
        try:
            from app.services.watermark_service import load_rules
            watermark_patterns = await load_rules(db)
        except Exception as exc:
            logger.warning("resume: watermark load_rules failed (%s); using defaults", exc)
        if not watermark_patterns:
            from app.services.watermark_service import get_default_patterns
            watermark_patterns = get_default_patterns()

    shared: dict = {
        "import_mode": import_mode,
        "strategy": strategy,
        "watermark_patterns": watermark_patterns,
    }

    # Rebuild GlobalHashIndex: recent_days window + every batch_id this
    # pipeline already wrote, so resumed chunks can dedupe against their
    # successful siblings.
    hash_index: GlobalHashIndex | None = GlobalHashIndex()
    try:
        async with session_factory() as init_db:
            await hash_index.load(init_db, batch_ids=completed_batch_ids or None)
    except Exception:
        logger.exception(
            "resume: GlobalHashIndex.load failed; similarity match will fallback"
        )
        hash_index = None
    if hash_index is not None:
        shared["hash_index"] = hash_index

    async with session_factory() as init_db:
        seen_hashes = await _load_seen_hashes_for_resume(init_db, pipeline_id)

    # Mark the pipeline running again so status queries reflect the in-progress
    # resume and a concurrent second resume can detect the conflict.
    async with session_factory() as init_db:
        await ckpt.update_pipeline_status(init_db, pipeline_id, status="running")
    await ckpt.invalidate_progress_cache(pipeline_id)

    pipeline = ImportPipeline(options=opts)
    pipeline.pipeline_id = pipeline_id
    started_at = datetime.now().isoformat()

    chunk_results: list[dict] = []
    any_chunk_failed = False
    try:
        for chunk in pending:
            # P0-3: 每个 chunk 一个独立 session（事务边界 = chunk 边界）。
            async with session_factory() as chunk_db:
                outcome = await pipeline._execute_chunk(
                    chunk_index=chunk.chunk_index,
                    page_start=chunk.page_start,
                    logical_end=chunk.page_end,
                    total_pages=total_pages,
                    is_last_chunk=(chunk.chunk_index == max_chunk_index),
                    chunk_overlap=chunk_overlap,
                    file_content=None,
                    file_path=file_path,
                    source_type=pipeline_row.source_type or "pdf",
                    source_file=pipeline_row.source_file or "",
                    subject=subject,
                    subject_id=subject_id,
                    opts=opts,
                    db=chunk_db,
                    shared=shared,
                    progress_callback=None,
                    started_at=started_at,
                    seen_hashes=seen_hashes,
                    hash_index=hash_index,
                    page_image_refs=None,
                )
            chunk_results.append(outcome)
            if outcome["status"] == "failed":
                any_chunk_failed = True
    finally:
        # P1-1: 清空 hash_index 内部 dict，避免 resume 路径异常时大字典残留。
        if hash_index is not None:
            hash_index._question_index.clear()
            hash_index._import_index.clear()

    # Recompute overall status from current DB state — chunks not in
    # ``pending`` could still be ``failed`` if a prior resume left them so;
    # also covers the case where an earlier chunk silently regressed (we
    # never overwrite completed chunks here).
    async with session_factory() as final_db:
        progress = await ckpt.get_pipeline_progress(final_db, pipeline_id, use_cache=False)
        still_failing = (progress and progress.get("failed_chunks", 0) > 0)
        overall_status = "paused" if (any_chunk_failed or still_failing) else "completed"
        await ckpt.update_pipeline_status(
            final_db,
            pipeline_id,
            status=overall_status,
            finished=(overall_status == "completed"),
        )
    await ckpt.invalidate_progress_cache(pipeline_id)


async def run_excel_pipeline_background(
    pipeline_id: str,
    file_content: bytes,
    source_file: str,
    import_excel_fn,
) -> None:
    """后台运行 Excel 导入，结果写入 Redis + 内存以支持状态查询。"""
    from app.core.database import async_session

    await _set_pipeline_store(pipeline_id, {
        "pipeline_id": pipeline_id,
        "status": "parsing",
        "source_type": "excel",
        "stages": {"extract": {"status": "running"}},
        "stats": {},
        "errors": [],
        "started_at": datetime.now().isoformat(),
    })

    try:
        async with async_session() as db:
            batch_id, total = await import_excel_fn(db, file_content, source_file)
        # P0-1: release Excel bytes after import function consumes them
        del file_content
        await _set_pipeline_store(pipeline_id, {
            "pipeline_id": pipeline_id,
            "status": "completed",
            "source_type": "excel",
            "batch_id": batch_id,
            "stats": {"total": total, "to_review": total},
            "stages": {"extract": {"status": "completed"}},
            "errors": [],
            "started_at": _pipeline_store[pipeline_id]["started_at"],
            "finished_at": datetime.now().isoformat(),
        })
    except Exception as exc:
        logger.exception("Excel pipeline %s failed", pipeline_id)
        await _set_pipeline_store(pipeline_id, {
            "pipeline_id": pipeline_id,
            "status": "failed",
            "source_type": "excel",
            "errors": [str(exc)],
            "started_at": _pipeline_store.get(pipeline_id, {}).get("started_at", ""),
            "finished_at": datetime.now().isoformat(),
        })


async def get_pipeline_status(pipeline_id: str, db=None) -> dict | None:
    """查询流水线状态（Redis + 内存 fallback）。

    P0-3: 主 store 已瘦身，本函数把 diagnostics 从独立 KV 合并回去，
    对外返回与改造前一致的完整视图。

    P2-6: 当 ``db`` 注入时，从 import_pipelines / import_pipeline_chunks 拉
    chunk 进度并合并到 ``chunk_progress`` 字段。db=None 或无 chunk 记录时省
    略该字段，向后兼容图片 / Excel / 单 pass 等无 chunk 场景。

    P2-resume-store: ``resume_pipeline_background`` 只更新 DB 的
    ``import_pipelines.status``，不回写 ``_pipeline_store`` 主 store——首次
    导入结束时写入的 ``status="paused"`` 在内存里会一直停在这里，导致 resume
    途中（running）和 resume 完成（completed）期间前端轮询拿到的还是 paused。
    chunked 路径下 ``chunk_progress.status`` 来自 DB 权威源，因此当 chunk
    进度可用时用它覆盖顶层 ``status``，不为 chunked 路径之外的场景（image /
    excel / 单 pass）引入新行为。
    """
    data = await _get_pipeline_store(pipeline_id)
    if data is None:
        return None
    # 防御性拷贝：_get_pipeline_store 返回的是 _pipeline_store 内引用，
    # 任何后续字段写入都会直接污染主 store（白名单契约破坏）。
    data = dict(data)
    diagnostics = await _get_pipeline_diagnostics(pipeline_id)
    if diagnostics is not None:
        data["diagnostics"] = diagnostics
    if pipeline_id in _ocr_progress:
        data["ocr_progress"] = _ocr_progress[pipeline_id]

    if db is not None:
        try:
            from app.features import pipeline_checkpoint as ckpt

            progress = await ckpt.get_pipeline_progress(
                db, pipeline_id, use_cache=True
            )
            if progress is not None:
                data["chunk_progress"] = progress
                db_status = progress.get("status")
                if db_status:
                    data["status"] = db_status
        except Exception:
            logger.debug(
                "fetch chunk_progress for %s failed", pipeline_id, exc_info=True
            )
    return data
