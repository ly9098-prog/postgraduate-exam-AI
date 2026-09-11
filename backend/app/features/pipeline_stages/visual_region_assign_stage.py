"""Visual region assignment stage — assign page-level visual regions to questions.

This stage MUST run AFTER question splitter and match stage, so that each
question has known spatial boundaries (page_start, page_end, option regions).

Assignment rules:
1. Visual region between a question's start bbox and the next question's start bbox → assign to this question
2. Spatial overlap with stem/options region → assign to overlapping question (highest IoU wins)
3. Region inside an option area (A/B/C/D) → assign with option_key
4. Cross-page: region at top of next page can be assigned to previous page's question
5. Ambiguous (overlaps two questions) → requires_review=True, visual_region_ambiguous
6. Unassignable → visual_region_unassigned
"""

from __future__ import annotations

import logging
import re

from app.features.pipeline_stages._helpers import _count_risk_flags
from app.services.visual_region_types import (
    AssignmentMethod,
)

logger = logging.getLogger(__name__)

# IoU threshold for "strong overlap"
_STRONG_IOU_THRESHOLD = 0.3

# y-distance threshold (in normalized units) for "between questions" assignment
_BETWEEN_QUESTIONS_Y_THRESHOLD = 100


def run_visual_region_assign_stage(
    questions: list[dict],
    *,
    page_regions: dict[int, list[dict]] | None = None,
) -> dict:
    """Assign page-level visual regions to the correct questions.

    Args:
        questions: Pipeline question dicts (post-split, post-match).
            Each should have page_start, page_end, and optionally
            option_spatial_bounds or similar bbox info.
        page_regions: Page index → list of VisualRegion dicts
            (as produced by visual_region_detect_stage).

    Returns:
        dict with ``questions``, ``warnings``, ``risk_flag_counts`` keys.
    """
    if not questions:
        return {
            "questions": questions,
            "warnings": ["visual_region_assign: empty questions"],
        }

    warnings: list[str] = []
    assigned_count = 0
    unassigned_count = 0
    ambiguous_count = 0

    if not page_regions:
        # Reconstruct from questions' visual_regions if available
        page_regions = _collect_page_regions(questions)

    if not page_regions:
        warnings.append("visual_region_assign: no visual regions to assign")
        return {
            "questions": questions,
            "warnings": warnings,
            "risk_flag_counts": _count_risk_flags(questions),
        }

    # Build spatial index of questions by page
    questions_by_page: dict[
        int, list[tuple[int, dict]]
    ] = {}  # page → [(question_index, question_dict)]
    for idx, q in enumerate(questions):
        page = q.get("page_start") or 1
        questions_by_page.setdefault(page, []).append((idx, q))

    # Also track next-page questions for cross-page assignment
    next_page_questions: dict[int, list[tuple[int, dict]]] = {}
    for page, qs in questions_by_page.items():
        if page + 1 in questions_by_page:
            next_page_questions[page] = questions_by_page[page + 1]

    # Process each page's regions
    for page_idx, regions in page_regions.items():
        qs_on_page = questions_by_page.get(page_idx, [])
        if not qs_on_page and not next_page_questions.get(page_idx):
            # No questions on this page — mark regions as unassigned
            for region in regions:
                _mark_unassigned(region)
                unassigned_count += 1
            continue

        for region in regions:
            target_questions = qs_on_page
            assignment = _assign_region_to_question(region, qs_on_page, page_idx)

            if assignment["method"] == AssignmentMethod.UNASSIGNED:
                # Try cross-page assignment
                next_qs = next_page_questions.get(page_idx, [])
                if next_qs:
                    cross = _assign_region_to_question(region, next_qs, page_idx + 1)
                    if cross["method"] != AssignmentMethod.UNASSIGNED:
                        assignment = cross
                        assignment["method"] = AssignmentMethod.PAGE_CROSS
                        target_questions = next_qs
                        # Mark the target question as cross-page
                        q_idx, target_q = next_qs[cross["question_index"]]
                        if "cross_page_regions" not in target_q:
                            target_q["cross_page_regions"] = []
                        target_q["cross_page_regions"].append(region)
                        warnings.append(
                            f"region {region.get('region_id')} assigned cross-page "
                            f"from page {page_idx} to question on page {page_idx + 1}"
                        )

            if assignment["method"] == AssignmentMethod.UNASSIGNED:
                _mark_unassigned(region)
                unassigned_count += 1
                continue

            # Apply assignment to the target question
            q_idx, target_q = target_questions[assignment["question_index"]]
            _attach_region_to_question(target_q, region, assignment)

            if assignment.get("ambiguous"):
                ambiguous_count += 1
            else:
                assigned_count += 1

    total = assigned_count + unassigned_count + ambiguous_count
    if total:
        warnings.append(
            f"visual_region_assign: {assigned_count} assigned, "
            f"{ambiguous_count} ambiguous, {unassigned_count} unassigned"
        )

    return {
        "questions": questions,
        "warnings": warnings,
        "risk_flag_counts": _count_risk_flags(questions),
    }


def _collect_page_regions(questions: list[dict]) -> dict[int, list[dict]]:
    """Reconstruct page_regions from visual_regions on question dicts."""
    page_regions: dict[int, list[dict]] = {}
    seen: set[str] = set()
    for q in questions:
        for vr in q.get("visual_regions") or []:
            if isinstance(vr, dict):
                region_id = str(vr.get("region_id") or "")
                if region_id and region_id in seen:
                    continue
                if region_id:
                    seen.add(region_id)
                page = vr.get("source_page") or q.get("page_start") or 1
                page_regions.setdefault(page, []).append(vr)
    return page_regions


def _assign_region_to_question(
    region: dict,
    questions_on_page: list[tuple[int, dict]],
    page_idx: int,
) -> dict:
    """Determine which question a region belongs to.

    Returns dict with:
        question_index: int (index into questions_on_page)
        method: AssignmentMethod
        ambiguous: bool
        assignment_confidence: float
        option_key: str | None
    """
    if not questions_on_page:
        return {
            "question_index": -1,
            "method": AssignmentMethod.UNASSIGNED,
            "ambiguous": False,
            "assignment_confidence": 0.0,
            "option_key": None,
        }

    region_bbox = region.get("bbox")
    if not region_bbox or len(region_bbox) != 4:
        text_match = _assign_region_by_text(region, questions_on_page)
        if text_match is not None:
            return text_match
        return {
            "question_index": 0 if len(questions_on_page) == 1 else -1,
            "method": AssignmentMethod.UNASSIGNED
            if len(questions_on_page) > 1
            else AssignmentMethod.BBOX_OVERLAP,
            "ambiguous": len(questions_on_page) > 1,
            "assignment_confidence": 0.1,
            "option_key": None,
        }

    # Strategy 1: Check option_key if region is inside an option area
    for position, (_question_index, q) in enumerate(questions_on_page):
        option_key = _find_region_in_options(region, q)
        if option_key:
            return {
                "question_index": position,
                "method": AssignmentMethod.OPTION_REGION,
                "ambiguous": False,
                "assignment_confidence": 0.9,
                "option_key": option_key,
            }

    # Strategy 2: IoU overlap with question stem/option spatial bounds
    best_match = -1
    best_iou = 0.0
    for position, (_question_index, q) in enumerate(questions_on_page):
        q_bbox = _get_question_bbox(q)
        if q_bbox:
            iou = _compute_iou(region_bbox, q_bbox)
            if iou > best_iou:
                best_iou = iou
                best_match = position

    if best_match >= 0 and best_iou >= _STRONG_IOU_THRESHOLD:
        return {
            "question_index": best_match,
            "method": AssignmentMethod.BBOX_OVERLAP,
            "ambiguous": False,
            "assignment_confidence": min(best_iou + 0.3, 0.95),
            "option_key": None,
        }

    # Strategy 3: Between-questions — region falls between start of question A
    # and start of question B → assign to question A
    if len(questions_on_page) >= 2:
        sorted_qs = sorted(
            enumerate(questions_on_page),
            key=lambda item: _get_question_top_y(item[1][1]),
        )
        region_top = region_bbox[1]
        for i in range(len(sorted_qs) - 1):
            current_position, (_current_index, current_question) = sorted_qs[i]
            _next_position, (_next_index, next_question) = sorted_qs[i + 1]
            q_top = _get_question_top_y(current_question)
            next_q_top = _get_question_top_y(next_question)
            if q_top <= region_top <= next_q_top:
                # Check if region is also close to the next question
                dist_to_next = next_q_top - region_top
                if dist_to_next < _BETWEEN_QUESTIONS_Y_THRESHOLD * 0.3:
                    # Too close to the next question — ambiguous
                    return {
                        "question_index": current_position,
                        "method": AssignmentMethod.BETWEEN_QUESTIONS,
                        "ambiguous": True,
                        "assignment_confidence": 0.5,
                        "option_key": None,
                    }
                return {
                    "question_index": current_position,
                    "method": AssignmentMethod.BETWEEN_QUESTIONS,
                    "ambiguous": False,
                    "assignment_confidence": 0.7,
                    "option_key": None,
                }

    # Fallback: attach to the only question on this page
    if len(questions_on_page) == 1:
        return {
            "question_index": 0,
            "method": AssignmentMethod.UNCERTAIN,
            "ambiguous": False,
            "assignment_confidence": 0.4,
            "option_key": None,
        }

    # Multiple questions but no clear match — unassigned
    return {
        "question_index": -1,
        "method": AssignmentMethod.UNASSIGNED,
        "ambiguous": False,
        "assignment_confidence": 0.0,
        "option_key": None,
    }


def _assign_region_by_text(
    region: dict,
    questions_on_page: list[tuple[int, dict]],
) -> dict | None:
    """Assign coordinate-free provider tables by literal cell/text overlap."""
    source = region.get("table_source") or region.get("raw_data") or {}
    snippets = _collect_distinctive_strings(source)
    if not snippets:
        return None

    scored: list[tuple[int, int]] = []
    for position, (_question_index, question) in enumerate(questions_on_page):
        haystack = "\n".join(
            str(value or "")
            for value in (
                question.get("stem"),
                (question.get("parsed_content") or {}).get("text"),
                question.get("raw_text"),
            )
        )
        normalized_haystack = re.sub(r"\s+", "", haystack).lower()
        score = sum(
            min(len(snippet), 40)
            for snippet in snippets
            if re.sub(r"\s+", "", snippet).lower() in normalized_haystack
        )
        scored.append((score, position))

    scored.sort(reverse=True)
    # One distinctive five-character cell value (for example a process or
    # algorithm name) is sufficient when it matches only one question.
    if not scored or scored[0][0] < 4:
        return None
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return {
        "question_index": scored[0][1],
        "method": AssignmentMethod.UNCERTAIN,
        "ambiguous": False,
        "assignment_confidence": min(0.85, 0.45 + scored[0][0] / 100),
        "option_key": None,
    }


def _collect_distinctive_strings(value, depth: int = 0) -> list[str]:
    if depth > 5:
        return []
    results: list[str] = []
    if isinstance(value, str):
        # Prefer complete cell-like lines, then stable word/number chunks.
        for line in re.split(r"[\r\n|]", value):
            text = re.sub(r"<[^>]+>", " ", line).strip(" -:\t")
            if 3 <= len(text) <= 80:
                results.append(text)
        return list(dict.fromkeys(results))[:40]
    if isinstance(value, dict):
        for key in (
            "text",
            "content",
            "markdown",
            "html",
            "caption",
            "headers",
            "rows",
            "cells",
        ):
            if key in value:
                results.extend(_collect_distinctive_strings(value[key], depth + 1))
    elif isinstance(value, (list, tuple)):
        for item in value[:200]:
            results.extend(_collect_distinctive_strings(item, depth + 1))
    return list(dict.fromkeys(results))[:80]


def _attach_region_to_question(
    question: dict,
    region: dict,
    assignment: dict,
) -> None:
    """Attach a visual region to a question as a segment and visual_regions entry."""
    vr = dict(region)
    vr["assignment_method"] = (
        assignment["method"].value
        if hasattr(assignment["method"], "value")
        else str(assignment["method"])
    )
    vr["assignment_confidence"] = assignment["assignment_confidence"]
    vr["option_key"] = assignment.get("option_key")
    vr["requires_review"] = bool(
        assignment.get("ambiguous")
        or assignment["assignment_confidence"] < 0.65
        or assignment["method"]
        in {AssignmentMethod.UNCERTAIN, AssignmentMethod.PAGE_CROSS}
    )

    # Store in visual_regions list
    q_vrs: list[dict] = list(question.get("visual_regions") or [])
    # Don't duplicate
    if not any(r.get("region_id") == vr.get("region_id") for r in q_vrs):
        q_vrs.append(vr)
    question["visual_regions"] = q_vrs

    # Add risk flags
    flags = list(question.get("risk_flags") or [])
    if assignment.get("ambiguous"):
        if "visual_region_ambiguous" not in flags:
            flags.append("visual_region_ambiguous")
    if assignment["method"] == AssignmentMethod.UNASSIGNED:
        if "visual_region_unassigned" not in flags:
            flags.append("visual_region_unassigned")
    # Remove visual_region_detected (replaced by more specific flags)
    if assignment["method"] != AssignmentMethod.UNASSIGNED:
        if "visual_region_detected" not in flags:
            flags.append("visual_region_detected")
    if flags:
        question["risk_flags"] = flags


def _mark_unassigned(region: dict) -> None:
    """Mark a region as unassigned."""
    region["assignment_method"] = "unassigned"
    region["assignment_confidence"] = 0.0
    region["requires_review"] = True


def _find_region_in_options(region: dict, question: dict) -> str | None:
    """Check if a region falls within any option's spatial area.

    Returns the option key (A/B/C/D) or None.
    """
    option_spatial = question.get("option_spatial_bounds") or {}
    region_bbox = region.get("bbox")
    if not region_bbox or len(region_bbox) != 4:
        return None

    rx0, ry0, rx1, ry1 = region_bbox[:4]
    region_area = (rx1 - rx0) * (ry1 - ry0)
    if region_area <= 0:
        return None

    best_key = None
    best_overlap = 0.0

    for opt_key, opt_bbox in option_spatial.items():
        if not opt_bbox or len(opt_bbox) != 4:
            continue
        ox0, oy0, ox1, oy1 = opt_bbox[:4]
        # Compute intersection
        ix0 = max(rx0, ox0)
        iy0 = max(ry0, oy0)
        ix1 = min(rx1, ox1)
        iy1 = min(ry1, oy1)
        if ix1 > ix0 and iy1 > iy0:
            overlap_area = (ix1 - ix0) * (iy1 - iy0)
            if overlap_area > best_overlap:
                best_overlap = overlap_area
                best_key = opt_key

    # Region must cover > 40% of the option area to be considered in-option
    if best_key and best_overlap > 0:
        opt_bbox = option_spatial[best_key]
        opt_area = (opt_bbox[2] - opt_bbox[0]) * (opt_bbox[3] - opt_bbox[1])
        if opt_area > 0 and best_overlap / opt_area > 0.4:
            return best_key

    return None


def _get_question_bbox(question: dict) -> list[float] | None:
    """Get the spatial bounding box of a question (stem + options area)."""
    bbox = question.get("question_bbox")
    if bbox and len(bbox) == 4:
        return bbox
    # Try to construct from page_start, page_end, and option bounds
    return None


def _get_question_top_y(question: dict) -> float:
    """Get the top y-coordinate of a question for ordering."""
    q_bbox = _get_question_bbox(question)
    if q_bbox:
        return q_bbox[1]
    # Fallback: use question number as proxy
    return float(question.get("number", 0)) * 100


def _compute_iou(bbox_a: list[float], bbox_b: list[float]) -> float:
    """Compute Intersection over Union of two bboxes."""
    ax0, ay0, ax1, ay1 = bbox_a[:4]
    bx0, by0, bx1, by1 = bbox_b[:4]

    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)

    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0

    intersection = (ix1 - ix0) * (iy1 - iy0)
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0
