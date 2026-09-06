"""Build snapshot data — extracts full question content for stable re-export."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wrong_question import WrongQuestion
from app.services.export.analysis_content import resolve_preferred_analysis
from app.services.export.question_content import (
    extract_blank_option_groups,
    extract_option_text,
    extract_question_text,
    has_visual_question_content,
    iter_question_image_urls,
)
from app.services.question_revision_service import load_revision_kp_names, load_revision_views

logger = logging.getLogger(__name__)

_MAX_CONTENT_LENGTH = 100 * 1024  # 100 KB per question snapshot


async def build_snapshot_data(
    db: AsyncSession,
    user_id: int,
    wq_ids: list[int],
    wq_order_map: dict[int, int],
    config: dict,
) -> dict:
    """Build the full snapshot data dict from resolved/sorted WQ IDs.

    Returns:
        A dict with:
        - ``questions``: ordered list of question data dicts
        - ``config``: the export config
        - ``user_id``: int
        - ``total_count``: int
    """
    rows = list((await db.scalars(
        select(WrongQuestion).where(WrongQuestion.id.in_(wq_ids))
    )).all())
    revision_ids = [int(wq.question_version_id) for wq in rows]
    views = await load_revision_views(db, revision_ids)

    # Order by the sorted wq_ids. Keep the WrongQuestion row together with the
    # immutable revision because user AI analysis is per wrong row while the bank
    # analysis/content must be reproduced from the revision the user actually saw.
    wq_map = {wq.id: wq for wq in rows}
    kp_map = await load_revision_kp_names(db, revision_ids)

    questions_data = []
    skip_count = 0
    skip_reasons: dict[str, int] = {}

    for wq_id in wq_ids:
        row = wq_map.get(wq_id)
        if row is None:
            skip_count += 1
            skip_reasons.setdefault("题目数据不存在", 0)
            skip_reasons["题目数据不存在"] += 1
            continue

        wq = row
        q = views.get(int(wq.question_version_id))
        if q is None:
            skip_count += 1
            skip_reasons.setdefault("题目版本不存在", 0)
            skip_reasons["题目版本不存在"] += 1
            continue
        kps = kp_map.get(int(wq.question_version_id), [])

        # Validate and normalize core content. Older imported questions can
        # store their visible stem in text segments or raw_content rather than
        # content.stem/content.text. Keep image-only stems as valid questions.
        content = dict(q.content) if isinstance(q.content, dict) else {}
        stem = extract_question_text(q)
        if not stem and not has_visual_question_content(q):
            skip_count += 1
            skip_reasons.setdefault("题干为空", 0)
            skip_reasons["题干为空"] += 1
            continue
        if stem and not (content.get("stem") or content.get("text")):
            content["stem"] = stem

        # For choice questions, validate options. Multi-blank choices use
        # content.blank_option_groups by design and normally leave top-level
        # q.options empty, so they need a dedicated extraction path.
        is_standard_choice = q.question_type in ("single_choice", "multiple_choice")
        is_multi_blank_choice = q.question_type == "multi_blank_choice"
        options = _normalize_options(q.options)
        blank_option_groups = extract_blank_option_groups(q) if is_multi_blank_choice else []
        if is_standard_choice and not options:
            skip_count += 1
            skip_reasons.setdefault("选择题缺少选项", 0)
            skip_reasons["选择题缺少选项"] += 1
            continue
        if is_multi_blank_choice and not blank_option_groups:
            skip_count += 1
            skip_reasons.setdefault("多空选择题缺少选项", 0)
            skip_reasons["多空选择题缺少选项"] += 1
            continue
        if blank_option_groups and not (content.get("blank_option_groups") or content.get("blank_groups")):
            # Freeze the recovered legacy shape into the export snapshot so
            # later re-export does not depend on mutable compatibility logic.
            content["blank_option_groups"] = blank_option_groups

        # Extract subject info
        subject_label = _get_subject_label(q)

        q_data = {
            "wrong_question_id": wq_id,
            "question_id": q.question_id,
            "question_version_id": q.question_version_id,
            "question_type": q.question_type,
            "content": content,
            "raw_content": q.raw_content or "",
            "options": options,
            "blank_option_groups": blank_option_groups,
            "answer": q.answer or "",
            # Match wrong-detail: prefer wrong_questions.ai_analysis, then
            # questions.analysis, and turn structured JSON into readable
            # sections instead of printing the raw payload into the file.
            "analysis": resolve_preferred_analysis(wq.ai_analysis, q.analysis),
            "subject": {"id": q.subject_id, "label": subject_label} if subject_label else {"id": q.subject_id},
            "knowledge_points": kps,
            "primary_knowledge_point": _get_primary_kp(kps),
            "image_urls": iter_question_image_urls(q),
            "source": q.source,
        }

        questions_data.append(q_data)

    # Build group metadata and physically keep each group together. The
    # requested sort order still controls the order *inside* each group.
    # Question-type groups use the product's canonical type order; the other
    # grouping modes keep the order in which a group first appears after sort.
    group_by = config.get("group_by", "none")
    if group_by != "none":
        for q_data in questions_data:
            q_data["_group_title"] = _get_group_title(q_data, group_by)
        questions_data = _order_questions_for_grouping(questions_data, group_by)

    return {
        "questions": questions_data,
        "config": config,
        "user_id": user_id,
        "total_count": len(wq_ids),
        "success_count": len(questions_data),
        "skip_count": skip_count,
        "skip_reasons": skip_reasons if skip_reasons else None,
    }



def _normalize_options(options) -> dict[str, str]:
    """Return printable option text for plain and rich option payloads."""
    if not isinstance(options, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in options.items():
        text = extract_option_text(value)
        if text:
            normalized[str(key)] = text
    return normalized


def _get_subject_label(q):
    """Get subject display name."""
    try:
        if q.subject_ref:
            return q.subject_ref.name
    except Exception:
        pass
    return None


def _get_primary_kp(kps):
    """Return the first knowledge point (order preserved by position)."""
    if kps:
        first = kps[0]
        if isinstance(first, dict):
            for key in ("name", "label", "title", "id"):
                value = first.get(key)
                if value not in (None, ""):
                    return str(value)
            return None
        return str(first)
    return None


def _get_group_title(q_data: dict, group_by: str) -> str:
    """Generate group title for a question."""
    if group_by == "subject":
        return q_data.get("subject", {}).get("label", "") or "其他"
    if group_by == "knowledge_point":
        return q_data.get("primary_knowledge_point", "") or "其他知识点"
    if group_by == "question_type":
        from app.features.question_type import QUESTION_TYPE_LABELS, QuestionType
        qt = q_data.get("question_type", "")
        try:
            return QUESTION_TYPE_LABELS.get(QuestionType(qt), qt) or "其他"
        except (ValueError, KeyError):
            return qt or "其他"
    if group_by == "chapter":
        return q_data.get("source", "") or "其他"
    return ""


def _order_questions_for_grouping(questions: list[dict], group_by: str) -> list[dict]:
    """Return questions with each export section kept contiguous.

    Sorting is performed before snapshot construction. This function performs a
    stable partition only: it never changes the relative order of questions
    that belong to the same group.
    """
    if not questions or group_by == "none":
        return questions

    groups: dict[str, list[dict]] = {}
    first_seen: dict[str, int] = {}
    for index, question in enumerate(questions):
        title = question.get("_group_title", "") or "其他"
        if title not in groups:
            groups[title] = []
            first_seen[title] = index
        groups[title].append(question)

    if group_by == "question_type":
        from app.features.question_type import QUESTION_TYPE_SORT_ORDER, QuestionType

        def group_rank(item: tuple[str, list[dict]]) -> tuple[int, int, str]:
            title, items = item
            code = items[0].get("question_type", "") if items else ""
            try:
                rank = QUESTION_TYPE_SORT_ORDER.get(QuestionType(code), 999)
            except (ValueError, KeyError):
                rank = 999
            return rank, first_seen[title], title

        ordered_groups = sorted(groups.items(), key=group_rank)
    else:
        ordered_groups = sorted(groups.items(), key=lambda item: first_seen[item[0]])

    return [question for _, items in ordered_groups for question in items]
