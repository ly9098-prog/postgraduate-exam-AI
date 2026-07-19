"""Structure Freeze Stage — detect and freeze option structures before splitting.

This stage runs after text normalization and before question splitting.
It detects option patterns in OCR blocks and produces frozen structures that
downstream stages read but never modify.

Design:
    - Single deterministic stage for option extraction
    - Pure regex-based detection (no AI, no heuristics)
    - Output is immutable — downstream stages (split, normalize, repair) only read
    - Each block is scanned; detected options are recorded in a registry
    - Options are bound to stable region/line IDs for merge/split resilience
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import types
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Binding status constants ─────────────────────────────────────────────

BINDING_BOUND = "bound"
BINDING_REPLACED = "replaced"
BINDING_MERGED = "merged"
BINDING_SPLIT = "split"
BINDING_LOST = "binding_lost"
BINDING_NEEDS_REVIEW = "needs_review"

# ── FrozenOptionEntry — stable-ID-based option binding ────────────────────


@dataclass
class FrozenOptionEntry:
    """单个冻结选项，绑定到稳定的 region_id/line_id。

    ``option_key``: A/B/C/D
    ``source_region_ids``: 此选项来源的 region ID 列表
    ``source_line_ids``: 此选项来源的 line ID 列表
    ``normalized_text``: 标准化后的选项文本
    ``binding_status``: 绑定状态 (bound/replaced/merged/split/binding_lost/needs_review)
    """
    option_key: str
    source_region_ids: list[str] = field(default_factory=list)
    source_line_ids: list[str] = field(default_factory=list)
    original_text: str = ""
    normalized_text: str = ""
    confidence: float = 1.0
    frozen_revision: int = 0
    binding_status: str = BINDING_BOUND
    needs_review: bool = False
    binding_reason_codes: list[str] = field(default_factory=list)

    def update_binding(
        self,
        new_region_ids: list[str] | None = None,
        new_line_ids: list[str] | None = None,
        status: str | None = None,
        reason_codes: list[str] | None = None,
    ) -> None:
        """Update binding after merge/split/replacement.

        Preserves original source IDs in ``source_region_ids`` / ``source_line_ids``.
        Sets new IDs for ongoing binding.
        """
        if status:
            self.binding_status = status
            self.frozen_revision += 1
        if reason_codes:
            self.binding_reason_codes = list(set(self.binding_reason_codes + reason_codes))
            if status in (BINDING_LOST, BINDING_NEEDS_REVIEW):
                self.needs_review = True
        if new_region_ids is not None:
            self.source_region_ids = list(set(self.source_region_ids + new_region_ids))
        if new_line_ids is not None:
            self.source_line_ids = list(set(self.source_line_ids + new_line_ids))


def update_frozen_entries_for_replacement(
    entries: list[FrozenOptionEntry],
    replacement_map: Any,
    case_dir: str = "",
) -> list[FrozenOptionEntry]:
    """Update frozen entries through a ReplacementMap chain.

    For each entry, traces its ``source_region_ids`` through the
    replacement map to find current bindings. Marks entries as
    ``binding_lost`` when no mapping exists.

    Args:
        entries: Current frozen option entries.
        replacement_map: ReplacementMap instance (or compatible object).
        case_dir: For diagnostics.

    Returns:
        Updated entries with current region IDs and binding status.
    """
    if not replacement_map:
        return entries

    updated: list[FrozenOptionEntry] = []
    for entry in entries:
        new_region_ids: list[str] = []
        any_lost = False
        reason_codes: list[str] = []

        for rid in entry.source_region_ids:
            current = _trace_replacement(rid, replacement_map, seen=None)
            if current:
                new_region_ids.extend(current)
            else:
                any_lost = True

        if any_lost:
            status = BINDING_LOST
            reason_codes.append("VL_REBUILD_REGION_MAPPING_FAILED")
        elif new_region_ids and new_region_ids != entry.source_region_ids:
            # Determine if it was a merge (fewer regions) or split (more regions)
            if len(new_region_ids) < len(entry.source_region_ids):
                status = BINDING_MERGED
            elif len(new_region_ids) > len(entry.source_region_ids):
                status = BINDING_SPLIT
            else:
                status = BINDING_REPLACED
        else:
            status = BINDING_BOUND

        entry.update_binding(
            new_region_ids=new_region_ids,
            status=status,
            reason_codes=reason_codes or None,
        )
        updated.append(entry)

    return updated


def _trace_replacement(
    region_id: str,
    replacement_map: Any,
    seen: set[str] | None = None,
) -> list[str] | None:
    """Trace a region ID through replacement chain with cycle protection.

    Follows ``ReplacementMap.lookup()`` until a terminal entry is found.
    Returns ``None`` if the ID is not found in any replacement chain.
    """
    if seen is None:
        seen = set()

    if region_id in seen:
        logger.warning("[FREEZE] Cycle detected in replacement chain: %s", region_id)
        return None

    seen.add(region_id)
    next_ids = replacement_map.lookup(region_id)

    if next_ids is None:
        # Terminal: region_id has no further replacements
        return [region_id]

    # Follow each next_id recursively
    results: list[str] = []
    for nid in next_ids:
        traced = _trace_replacement(nid, replacement_map, seen)
        if traced:
            results.extend(traced)
    return results or None


# ── DocumentIR-based freeze ──────────────────────────────────────────────


def freeze_from_document_ir(
    doc_ir: Any,
    **kwargs: Any,
) -> dict:
    """Extract and freeze options from DocumentIR regions.

    Scans each RegionIR's text for option patterns and produces
    ``FrozenOptionEntry`` instances bound to stable region/line IDs.

    Args:
        doc_ir: DocumentIR with ``.pages[].regions[].lines[]``.

    Returns:
        dict with:
            - ``frozen_option_registry`` (dict[str, list[FrozenOptionEntry]]):
              keyed by region_id
            - ``frozen_structures`` (list[dict]): serialized per-region structures
            - ``warnings`` (list[str])
    """
    registry: dict[str, list[FrozenOptionEntry]] = {}
    structures: list[dict] = []
    warnings: list[str] = []
    total_option_regions = 0

    if not hasattr(doc_ir, "pages") or not doc_ir.pages:
        return {
            "frozen_option_registry": registry,
            "frozen_structures": structures,
            "warnings": ["empty_document_ir"],
        }

    for page in doc_ir.pages:
        for region in page.regions:
            text = region.text
            if not text:
                continue

            options: dict[str, str] = {}
            option_line_ids: dict[str, list[str]] = {}

            lines = text.split("\n")
            for line in lines:
                inline_opts = _detect_inline_options(line)
                if inline_opts:
                    for k, v in inline_opts.items():
                        if k not in options:
                            options[k] = v
                else:
                    result = _detect_option_line(line)
                    if result:
                        key, opt_text = result
                        if key not in options:
                            options[key] = opt_text
                            for l in region.lines:
                                if key in l.text[:10]:
                                    option_line_ids.setdefault(key, []).append(l.line_id)

            if options:
                total_option_regions += 1
                entries: list[FrozenOptionEntry] = []
                for key, val in options.items():
                    entries.append(FrozenOptionEntry(
                        option_key=key,
                        source_region_ids=[region.region_id],
                        source_line_ids=option_line_ids.get(key, []),
                        original_text=val,
                        normalized_text=val,
                        confidence=region.confidence,
                        binding_status=BINDING_BOUND,
                    ))
                registry[region.region_id] = entries
                structures.append({
                    "region_id": region.region_id,
                    "page": page.page_index,
                    "options": dict(options),
                    "entries": [
                        {"option_key": e.option_key, "original_text": e.original_text,
                         "binding_status": e.binding_status, "source_region_ids": e.source_region_ids}
                        for e in entries
                    ],
                    "is_frozen": True,
                    "is_complete": options.keys() >= {"A", "B", "C", "D"},
                })

    if total_option_regions == 0:
        warnings.append("no_options_detected")

    return {
        "frozen_option_registry": registry,
        "frozen_structures": structures,
        "warnings": warnings,
    }


def freeze_registry_to_block_format(
    id_registry: dict[str, list[FrozenOptionEntry]],
) -> dict[str, dict[str, str]]:
    """Convert ID-based registry to legacy ``{region_id: {A: text, ...}}`` format.

    Used for backward compatibility with downstream stages that expect
    the old flat dict format.
    """
    legacy: dict[str, dict[str, str]] = {}
    for region_id, entries in id_registry.items():
        options: dict[str, str] = {}
        for entry in entries:
            options[entry.option_key] = entry.normalized_text
        if options:
            legacy[region_id] = options
    return legacy


# ── Option detection patterns ──────────────────────────────────────────────

# A. B. C. D. / A) B) / ①. ②. / (A) (B)
_OPTION_LINE_RE = re.compile(
    r"^\s*([A-Da-d]|[①②③④]|\(\s*[A-Da-d]\s*\))\s*[.、:：)）\s]"
)
# Inline: A.xxx B.xxx C.xxx D.xxx on same line
_INLINE_OPTION_RE = re.compile(
    r"([A-Da-d])\s*[.、:：)）]\s*"
    r"([^A-Da-d\n]+?)"
    r"(?=\s*[A-Da-d]\s*[.、:：)）]|\s*$)"
)
# Inline circled: ①.xxx ②.xxx ③.xxx ④.xxx on same line
_CIRCLED_INLINE_RE = re.compile(
    r"([①②③④])\s*[.、:：]\s*"
    r"([^①②③④\n]+?)"
    r"(?=\s*[①②③④]\s*[.、:：]|\s*$)"
)
# Inline paren: (A)xxx (B)xxx (C)xxx (D)xxx on same line
_PAREN_INLINE_RE = re.compile(
    r"\(\s*([A-Da-d])\s*\)\s*"
    r"([^(\n]+?)"
    r"(?=\s*\(\s*[A-Da-d]\s*\)|\s*$)"
)
# Circled digits
_CIRCLED_RE = re.compile(r"[①②③④]")
# Circled digit → ABCD mapping
_CIRCLED_MAP = {"①": "A", "②": "B", "③": "C", "④": "D"}


def _detect_option_line(line: str) -> tuple[str, str] | None:
    """Detect if a line starts with an option marker and extract (key, text)."""
    stripped = line.strip()
    if not stripped:
        return None
    m = _OPTION_LINE_RE.match(stripped)
    if m:
        raw_key = m.group(1)
        # Normalize key
        if raw_key in _CIRCLED_MAP:
            key = _CIRCLED_MAP[raw_key]
        else:
            key = raw_key.upper()
            key = re.sub(r"[()]", "", key).strip()
        text = _OPTION_LINE_RE.sub("", stripped).strip()
        if key in {"A", "B", "C", "D"} and text:
            return key, text
    return None


def _detect_inline_options(text: str) -> dict[str, str]:
    """Detect inline options like 'A.xxx B.xxx C.xxx D.xxx'."""
    options: dict[str, str] = {}

    # Priority 1: paren inline ((A) (B) (C) (D)) — must check before standard
    # inline since paren format also matches the broader inline regex.
    paren_matches = list(_PAREN_INLINE_RE.finditer(text))
    if len(paren_matches) >= 2:
        for m in paren_matches:
            key = m.group(1).upper()
            value = m.group(2).strip().rstrip("(").strip()
            if key in {"A", "B", "C", "D"} and value:
                options[key] = value
        return options

    # Priority 2: standard inline (A. B. C. D.)
    matches = list(_INLINE_OPTION_RE.finditer(text))
    if len(matches) >= 2:
        for m in matches:
            key = m.group(1).upper()
            value = m.group(2).strip()
            if key in {"A", "B", "C", "D"} and value:
                options[key] = value
        return options

    # Priority 3: circled inline (①. ②. ③. ④.)
    circled_matches = list(_CIRCLED_INLINE_RE.finditer(text))
    if len(circled_matches) >= 2:
        for m in circled_matches:
            raw_key = m.group(1)
            key = _CIRCLED_MAP.get(raw_key, raw_key)
            value = m.group(2).strip()
            if key in {"A", "B", "C", "D"} and value:
                options[key] = value
        return options

    return {}


# ── Freeze stage entry point ──────────────────────────────────────────────


def run_structure_freeze_stage(
    normalized_blocks: list[dict],
    **kwargs: Any,
) -> dict:
    """Scan normalized OCR blocks and freeze detected option structures.

    This is a pure, deterministic stage. It scans each block's text for
    option patterns and builds a ``frozen_option_registry`` — a mapping of
    ``(page, block_index)`` → detected options. Downstream stages use the
    registry instead of re-extracting options from text.

    Args:
        normalized_blocks: OCR blocks with ``normalized_text`` field.

    Returns:
        dict with:
            - ``frozen_option_registry`` (dict): ``{(page, block_idx): {A: text, ...}}``
            - ``frozen_structures`` (list[dict]): serialized per-block frozen structures
            - ``warnings`` (list[str])
    """
    if not normalized_blocks:
        logger.warning("[FREEZE] empty normalized_blocks")
        return {
            "frozen_option_registry": {},
            "frozen_structures": [],
            "warnings": ["empty_blocks"],
        }

    registry: dict[str, dict[str, str]] = {}
    structures: list[dict] = []
    warnings: list[str] = []
    total_option_blocks = 0

    for block in normalized_blocks:
        text = block.get("normalized_text") or block.get("text", "")
        if not text:
            continue

        page = block.get("page", 1)
        block_idx = block.get("block_index", 0)
        registry_key = f"{page}:{block_idx}"

        options: dict[str, str] = {}
        option_lines_found: list[int] = []
        style: str = "abcd"

        lines = text.split("\n")
        for li, line in enumerate(lines):
            # First check for inline options (e.g. A.甲 B.乙 C.丙 D.丁 on one line)
            inline_opts = _detect_inline_options(line)
            if inline_opts:
                for k, v in inline_opts.items():
                    if k not in options:
                        options[k] = v
                        option_lines_found.append(li)
                # Inline options found: skip single-line detection for this line
                # (inline is more precise)
            else:
                # Try single-line option detection
                result = _detect_option_line(line)
                if result:
                    key, opt_text = result
                    if key not in options:
                        options[key] = opt_text
                        option_lines_found.append(li)

            # Detect circled style
            if _CIRCLED_RE.search(line.strip()[:5]):
                style = "circled"

        if options:
            total_option_blocks += 1
            registry[registry_key] = dict(options)
            structures.append({
                "page": page,
                "block_index": block_idx,
                "options": dict(options),
                "option_style": style,
                "option_lines": option_lines_found,
                "option_keys": sorted(options.keys()),
                "confidence": _compute_confidence(options),
                "is_frozen": True,
                "is_complete": options.keys() >= {"A", "B", "C", "D"},
            })
            logger.debug(
                "[FREEZE] block %s:%s options=%s style=%s",
                page, block_idx, sorted(options.keys()), style,
            )

    if total_option_blocks == 0:
        warnings.append("no_options_detected")

    logger.info(
        "[FREEZE] stage complete: %d/%d blocks with options, %d structures frozen",
        total_option_blocks, len(normalized_blocks), len(structures),
    )

    # Compute checksum over the raw registry BEFORE freezing (so we can verify
    # downstream that the data hasn't been tampered with).
    checksum = _compute_freeze_checksum(registry)

    # Wrap registry in MappingProxyType for runtime immutability.
    # Any downstream attempt to mutate the frozen option data will raise
    # TypeError, enforcing the single-source-of-truth contract.
    immutable_registry = _freeze_deep_freeze(registry)

    return {
        "frozen_option_registry": immutable_registry,
        "frozen_structures": structures,
        "freeze_checksum": checksum,
        "warnings": warnings,
    }


def _compute_confidence(options: dict[str, str]) -> float:
    """Compute freeze confidence based on option completeness."""
    present = set(options.keys())
    required = {"A", "B", "C", "D"}
    missing = required - present

    if not missing:
        return 1.0
    if len(missing) <= 1:
        return 0.7
    if len(missing) <= 2:
        return 0.5
    return 0.3


def _compute_freeze_checksum(
    registry: dict[str, dict[str, str]],
) -> str:
    """Compute a deterministic SHA256 checksum over the frozen option registry.

    The checksum covers only the registry (the single source of truth),
    not the derived ``frozen_structures`` list (which may vary between runs
    due to non-essential metadata).

    Downstream stages can verify this checksum to detect any accidental
    modification of the frozen option data.
    """
    # Use sorted keys and a canonical JSON representation for determinism
    payload = json.dumps(registry, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _freeze_deep_freeze(registry: dict) -> dict[str, dict[str, str]]:
    """Recursively wrap the registry and all nested option dicts in MappingProxyType.

    This makes the entire frozen_option_registry read-only at runtime.
    Attempting to mutate it will raise a TypeError.
    """
    frozen: dict[str, dict[str, str]] = {}
    for key, opts in registry.items():
        frozen[key] = types.MappingProxyType(dict(opts))
    return types.MappingProxyType(frozen)  # type: ignore[return-value]


def run_structure_freeze_stage_from_ir(
    doc: "DocumentIR",
    **kwargs: Any,
) -> dict:
    """DocumentIR entry point for run_structure_freeze_stage."""
    from app.core.document_ir import document_ir_to_blocks
    blocks = document_ir_to_blocks(doc)
    return run_structure_freeze_stage(blocks, **kwargs)
