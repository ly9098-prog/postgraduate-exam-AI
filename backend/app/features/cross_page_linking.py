"""Cross-Page Linking — detect and link questions that span pages.

Uses DocumentIR page/region structure and stable IDs to identify
continuations, avoiding a separate text-gathering pass.

Heuristics (any single trigger is sufficient to consider a link):

1. Explicit continuation markers: ``（接上页）``, ``(续)``, ``继续`` at page start
2. First region(s) of a page start with option letters (A./B.) without a
   question number → likely continuation of previous page's question
3. First region(s) of a page start with lowercase text / continuation wording
   → likely mid-sentence continuation
4. Last region of previous page is near page bottom (y1 > 85% page_height)
   without sentence-ending punctuation → likely continues

Cross-page links are stored in the DocumentIR pipeline for artifact resume.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CrossPageLink:
    """Link between regions across pages for a single question.

    ``source_page_id`` / ``source_region_ids``: last page and its regions.
    ``target_page_id`` / ``target_region_ids``: next page and its regions.
    ``link_type``: ``"stem_contination"``, ``"option_continuation"``,
                   ``"answer_continuation"``.
    ``confidence``: 0.0 – 1.0
    ``reason_codes``: list of stable reason codes.
    """

    source_page_id: str
    target_page_id: str
    source_region_ids: list[str] = field(default_factory=list)
    target_region_ids: list[str] = field(default_factory=list)
    link_type: str = "stem_continuation"
    confidence: float = 0.5
    reason_codes: list[str] = field(default_factory=list)
    is_ambiguous: bool = False

    def to_dict(self) -> dict:
        return {
            "source_page_id": self.source_page_id,
            "target_page_id": self.target_page_id,
            "source_region_ids": list(self.source_region_ids),
            "target_region_ids": list(self.target_region_ids),
            "link_type": self.link_type,
            "confidence": round(self.confidence, 4),
            "reason_codes": list(self.reason_codes),
            "is_ambiguous": self.is_ambiguous,
        }


@dataclass
class CrossPageMergeResult:
    """Result of a cross-page block merge with full traceability.

    ``merged_block_id``: stable identifier for the merged block.
    ``source_block_ids``: block IDs contributing to the merged content.
    ``source_page_ids``: page IDs of all source blocks.
    ``source_region_ids``: region IDs of all source regions.
    ``applied_link_ids``: IDs of cross-page links applied in this merge.
    ``revision``: monotonically increasing revision counter for idempotency.
    ``link_confidence``: confidence of the strongest link applied.
    ``reason_codes``: all reason codes from applied links.
    """

    merged_block_id: str = ""
    source_block_ids: list[str] = field(default_factory=list)
    source_page_ids: list[str] = field(default_factory=list)
    source_region_ids: list[str] = field(default_factory=list)
    applied_link_ids: list[str] = field(default_factory=list)
    revision: int = 0
    link_confidence: float = 0.0
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "merged_block_id": self.merged_block_id,
            "source_block_ids": list(self.source_block_ids),
            "source_page_ids": list(self.source_page_ids),
            "source_region_ids": list(self.source_region_ids),
            "applied_link_ids": list(self.applied_link_ids),
            "revision": self.revision,
            "link_confidence": round(self.link_confidence, 4),
            "reason_codes": list(self.reason_codes),
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REASON_EXPLICIT_MARKER = "CROSS_PAGE_EXPLICIT_MARKER"
REASON_NO_QN_ON_FIRST_REGION = "CROSS_PAGE_NO_QN_FIRST_REGION"
REASON_PAGE_BEGINS_WITH_OPTIONS = "CROSS_PAGE_BEGINS_WITH_OPTIONS"
REASON_PAGE_BEGINS_WITH_LOWERCASE = "CROSS_PAGE_BEGINS_LOWERCASE"
REASON_PREV_NEAR_BOTTOM_NO_END = "CROSS_PAGE_PREV_NEAR_BOTTOM_NO_END"
REASON_AMBIGUOUS = "CROSS_PAGE_AMBIGUOUS"
REASON_NEW_QN_TERMINATES = "CROSS_PAGE_NEW_QN_TERMINATES"
REASON_HEADER_FOOTER_EXCLUDED = "CROSS_PAGE_HEADER_FOOTER_EXCLUDED"

from app.features.question_numbering import has_new_question_number

# Re-export as internal name for backward compatibility
_has_new_question_number = has_new_question_number

_EXPLICIT_CONT_RE = re.compile(
    r"(?:接上页|\(续\)|（续）|contin|上页|续表)",
    re.IGNORECASE,
)
_OPTION_START_RE = re.compile(r"^\s*[A-Da-d]\s*[.、:：)）\s]")
_SENTENCE_END_RE = re.compile(r"[。；!！?？：:]$")
_LOWERCASE_START_RE = re.compile(r"^\s*[a-z][a-z]")


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _get_page_text(page: Any) -> str:
    """Get full text of a page from its regions."""
    if not hasattr(page, "regions"):
        return ""
    texts: list[str] = []
    for region in page.regions:
        if hasattr(region, "text") and region.text:
            texts.append(str(region.text))
    return "\n".join(texts)


def _get_last_region_text(page: Any) -> str:
    """Get text of the last non-header/footer region."""
    if not hasattr(page, "regions") or not page.regions:
        return ""
    body_regions = [
        r
        for r in page.regions
        if getattr(r, "region_type", "") not in ("header", "footer", "watermark")
    ]
    if not body_regions:
        return ""
    last = body_regions[-1]
    return getattr(last, "text", "") or ""


def _get_first_region_text(page: Any) -> str:
    """Get text of the first non-header/footer region."""
    if not hasattr(page, "regions") or not page.regions:
        return ""
    body_regions = [
        r
        for r in page.regions
        if getattr(r, "region_type", "") not in ("header", "footer", "watermark")
    ]
    if not body_regions:
        return ""
    first = body_regions[0]
    return getattr(first, "text", "") or ""


def _is_near_bottom(page: Any) -> bool:
    """Check if the last body region is near the page bottom (y1 > 85% height)."""
    if not hasattr(page, "regions") or not page.regions:
        return False
    page_h = getattr(page, "height", 1000) or 1000
    body_regions = [
        r
        for r in page.regions
        if getattr(r, "region_type", "") not in ("header", "footer", "watermark")
    ]
    if not body_regions:
        return False
    last = body_regions[-1]
    bbox = getattr(last, "bbox", None)
    if bbox is None:
        return False
    return bbox.y1 > page_h * 0.85


def _starts_with_option(text: str) -> bool:
    """Check if text starts with an option marker (A./B./C./D.)."""
    first_line = text.strip().split("\n")[0]
    return bool(_OPTION_START_RE.match(first_line))


def _detect_explicit_continuation(page_text: str) -> bool:
    """Check for explicit continuation markers in the first 100 chars."""
    first_part = page_text.strip()[:100]
    return bool(_EXPLICIT_CONT_RE.search(first_part))


def _has_new_question_number(page_text: str) -> bool:
    """Check if the page starts with a new question number.

    Unified delegation to ``question_numbering``.
    """
    first_line = page_text.strip().split("\n")[0] if page_text else ""
    return has_new_question_number(first_line)


def _ends_without_sentence_end(text: str) -> bool:
    """Check if text doesn't end with sentence-ending punctuation."""
    if not text:
        return False
    text = text.strip()
    if not text:
        return False
    return not bool(_SENTENCE_END_RE.search(text[-5:]))


def _starts_with_lowercase(text: str) -> bool:
    """Check if text starts with lowercase (mid-sentence continuation)."""
    first_line = text.strip().split("\n")[0]
    return bool(_LOWERCASE_START_RE.match(first_line))


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------


def detect_cross_page_links(pages: list[Any]) -> list[CrossPageLink]:
    """Detect cross-page links between consecutive pages.

    Args:
        pages: List of PageIR objects from DocumentIR.

    Returns:
        List of CrossPageLink instances.
    """
    if not pages or len(pages) < 2:
        return []

    links: list[CrossPageLink] = []

    for i in range(len(pages) - 1):
        current_page = pages[i]
        next_page = pages[i + 1]

        current_text = _get_page_text(current_page)
        next_text = _get_page_text(next_page)

        if not current_text or not next_text:
            continue

        link = _evaluate_page_pair(current_page, next_page, current_text, next_text)
        if link is not None:
            links.append(link)

    return links


def _evaluate_page_pair(
    current_page: Any,
    next_page: Any,
    current_text: str,
    next_text: str,
) -> CrossPageLink | None:
    """Evaluate a single page pair for cross-page linking.

    Returns a ``CrossPageLink`` if a continuation is detected,
    ``None`` otherwise.
    """
    current_page_id = getattr(
        current_page, "page_id", f"p{getattr(current_page, 'page_index', 0)}"
    )
    next_page_id = getattr(
        next_page, "page_id", f"p{getattr(next_page, 'page_index', 0)}"
    )

    current_last_text = _get_last_region_text(current_page)
    next_first_text = _get_first_region_text(next_page)

    reasons: list[str] = []
    confidence = 0.0
    is_ambiguous = False

    # ── Signal 1: Explicit continuation marker ──
    if _detect_explicit_continuation(next_text):
        confidence = 0.9
        reasons.append(REASON_EXPLICIT_MARKER)

    # ── Signal 2: Previous page ends near bottom without sentence end ──
    prev_near_bottom = _is_near_bottom(current_page)
    prev_no_end = _ends_without_sentence_end(current_last_text)
    if prev_near_bottom and prev_no_end:
        confidence = max(confidence, 0.7)
        reasons.append(REASON_PREV_NEAR_BOTTOM_NO_END)

    # ── Signal 3: Next page starts without a new question number ──
    next_has_new_qn = _has_new_question_number(next_text)
    if not next_has_new_qn and confidence > 0:
        reasons.append(REASON_NO_QN_ON_FIRST_REGION)
    elif not next_has_new_qn and (
        prev_near_bottom
        or _starts_with_option(next_first_text)
        or _starts_with_lowercase(next_first_text)
    ):
        # No explicit marker but no new QN AND some continuation signal → weak link
        confidence = max(confidence, 0.3)
        reasons.append(REASON_NO_QN_ON_FIRST_REGION)

    # ── Signal 4: Next page starts with option letters ──
    if _starts_with_option(next_first_text):
        confidence = max(confidence, 0.7)
        if REASON_PAGE_BEGINS_WITH_OPTIONS not in reasons:
            reasons.append(REASON_PAGE_BEGINS_WITH_OPTIONS)

    # ── Signal 5: Next page starts with lowercase (mid-sentence) ──
    if _starts_with_lowercase(next_first_text):
        confidence = max(confidence, 0.5)
        reasons.append(REASON_PAGE_BEGINS_WITH_LOWERCASE)

    # ── No signals → no link ──
    if not reasons:
        return None

    # ── Ambiguity: both continuation AND new question number → contradicting signals ──
    if next_has_new_qn and confidence > 0:
        is_ambiguous = True
        reasons.append(REASON_AMBIGUOUS)
        confidence = min(confidence, 0.4)

    # Collect source/target region IDs
    source_region_ids: list[str] = []
    target_region_ids: list[str] = []
    if hasattr(current_page, "regions"):
        source_region_ids = [
            getattr(r, "region_id", "")
            for r in current_page.regions
            if getattr(r, "region_type", "") not in ("header", "footer", "watermark")
        ]
    if hasattr(next_page, "regions"):
        target_region_ids = [
            getattr(r, "region_id", "")
            for r in next_page.regions
            if getattr(r, "region_type", "") not in ("header", "footer", "watermark")
        ]

    # Determine link type
    link_type = "stem_continuation"
    if _starts_with_option(next_first_text):
        link_type = "option_continuation"
    elif _detect_explicit_continuation(next_text):
        link_type = "stem_continuation"

    link = CrossPageLink(
        source_page_id=current_page_id,
        target_page_id=next_page_id,
        source_region_ids=source_region_ids,
        target_region_ids=target_region_ids,
        link_type=link_type,
        confidence=round(confidence, 4),
        reason_codes=reasons,
        is_ambiguous=is_ambiguous,
    )

    return link


def apply_cross_page_links_to_pipeline(
    doc_ir: Any,
    cross_page_links: list[CrossPageLink],
    raw_questions: list[dict],
) -> list[dict]:
    """Merge cross-page linked questions in the pipeline output.

    For each cross-page link, finds the last question on the source page
    and appends the text from the linked target region(s).

    This is a simple heuristic merge — it doesn't re-run the splitter.
    For ambiguous links (is_ambiguous=True), questions are not merged
    but marked with a ``cross_page_ambiguous`` risk flag.

    Args:
        doc_ir: DocumentIR instance.
        cross_page_links: List of CrossPageLink instances.
        raw_questions: List of raw_question dicts from the pipeline.

    Returns:
        Updated raw_questions with merged cross-page content and risk flags.
    """
    if not cross_page_links or not raw_questions:
        return raw_questions

    # Build mapping: page_index → question indices on that page
    page_to_qs: dict[int, list[int]] = {}
    for qi, q in enumerate(raw_questions):
        ps = q.get("page_start", 1)
        page_to_qs.setdefault(ps, []).append(qi)

    for link in cross_page_links:
        # Get source page index
        source_pidx = _page_id_to_index(link.source_page_id, doc_ir)
        target_pidx = _page_id_to_index(link.target_page_id, doc_ir)

        if source_pidx is None or target_pidx is None:
            continue

        source_page = source_pidx + 1  # 1-based
        target_page = target_pidx + 1

        # Find last question on source page
        source_qis = page_to_qs.get(source_page, [])
        if not source_qis:
            continue

        last_qi = source_qis[-1]
        last_q = raw_questions[last_qi]

        if link.is_ambiguous:
            # Mark only, don't merge
            flags = list(last_q.get("risk_flags") or [])
            if "cross_page_ambiguous" not in flags:
                flags.append("cross_page_ambiguous")
            last_q["risk_flags"] = flags
            continue

        # Get target region text from DocumentIR
        target_text = _get_region_texts(
            doc_ir, link.target_page_id, link.target_region_ids
        )

        if not target_text:
            continue

        # Merge: append target text to last question's raw_question_text
        existing_text = last_q.get("raw_question_text", "") or ""
        if target_text not in existing_text:
            last_q["raw_question_text"] = existing_text + "\n" + target_text
            last_q["page_end"] = max(last_q.get("page_end", source_page), target_page)

        # Mark as cross-page
        flags = list(last_q.get("risk_flags") or [])
        if "cross_page_merged" not in flags:
            flags.append("cross_page_merged")
        last_q["risk_flags"] = flags

    return raw_questions


def _page_id_to_index(page_id: str, doc_ir: Any) -> int | None:
    """Convert a page_id string to a 0-based page index."""
    if not hasattr(doc_ir, "pages"):
        return None
    for i, page in enumerate(doc_ir.pages):
        if getattr(page, "page_id", "") == page_id:
            return i
    return None


def _get_region_texts(doc_ir: Any, page_id: str, region_ids: list[str]) -> str:
    """Get concatenated text for regions matching the given IDs on a page."""
    if not hasattr(doc_ir, "pages"):
        return ""
    for page in doc_ir.pages:
        if getattr(page, "page_id", "") != page_id:
            continue
        if not hasattr(page, "regions"):
            return ""
        texts: list[str] = []
        for region in page.regions:
            if getattr(region, "region_id", "") in region_ids:
                t = getattr(region, "text", "") or ""
                if t:
                    texts.append(str(t))
        return "\n".join(texts)
    return ""


# ---------------------------------------------------------------------------
# Pipeline stage entry point
# ---------------------------------------------------------------------------


def run_cross_page_linking_stage(
    doc_ir: Any,
    raw_questions: list[dict] | None = None,
) -> dict:
    """Run cross-page linking on a DocumentIR.

    Args:
        doc_ir: DocumentIR instance with pages.
        raw_questions: Optional list of raw_questions to update in-place.

    Returns:
        Dict with ``cross_page_links``, ``warnings``, and optionally
        ``raw_questions`` (if provided).
    """
    warnings: list[str] = []
    links: list[CrossPageLink] = []

    if not hasattr(doc_ir, "pages") or not doc_ir.pages:
        return {
            "cross_page_links": [],
            "warnings": ["No pages in DocumentIR"],
        }

    links = detect_cross_page_links(doc_ir.pages)

    for link in links:
        warn_parts: list[str] = [
            f"{link.source_page_id} → {link.target_page_id}",
            f"type={link.link_type}",
            f"conf={link.confidence}",
        ]
        if link.is_ambiguous:
            warn_parts.append("AMBIGUOUS")
        warnings.append(f"Cross-page link: {' '.join(warn_parts)}")

    result: dict = {
        "cross_page_links": [link.to_dict() for link in links],
        "warnings": warnings,
    }

    # Optionally merge into raw_questions
    if raw_questions is not None:
        merged = apply_cross_page_links_to_pipeline(doc_ir, links, raw_questions)
        result["raw_questions"] = merged

    return result
