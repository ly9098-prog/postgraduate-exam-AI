"""Build snapshot data — extracts full question content for stable re-export."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.question import Question
from app.models.wrong_question import WrongQuestion

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
    result = await db.execute(
        select(WrongQuestion, Question)
        .join(Question, WrongQuestion.question_id == Question.id)
        .where(WrongQuestion.id.in_(wq_ids))
        .options(selectinload(Question.subject_ref))
    )
    rows = result.fetchall()

    # Order by the sorted wq_ids
    wq_map = {}
    for wq, q in rows:
        wq_map[wq.id] = q

    questions_data = []
    skip_count = 0
    skip_reasons: dict[str, int] = {}

    for wq_id in wq_ids:
        q = wq_map.get(wq_id)
        if q is None:
            skip_count += 1
            skip_reasons.setdefault("题目数据不存在", 0)
            skip_reasons["题目数据不存在"] += 1
            continue

        # Validate and normalize core content. Older imported questions can
        # store their visible stem in text segments or raw_content rather than
        # content.stem/content.text. Keep image-only stems as valid questions.
        content = dict(q.content or {})
        stem = _extract_stem_text(content, q.raw_content)
        has_stem_image = _has_stem_image(content, q.image_url)
        if not stem and not has_stem_image:
            skip_count += 1
            skip_reasons.setdefault("题干为空", 0)
            skip_reasons["题干为空"] += 1
            continue
        if stem and not (content.get("stem") or content.get("text")):
            content["stem"] = stem

        # For choice questions, validate options
        is_choice = q.question_type in ("single_choice", "multiple_choice")
        options = q.options or {}
        if is_choice and not options:
            skip_count += 1
            skip_reasons.setdefault("选择题缺少选项", 0)
            skip_reasons["选择题缺少选项"] += 1
            continue

        # Extract subject info
        subject_label = _get_subject_label(q)

        q_data = {
            "wrong_question_id": wq_id,
            "question_id": q.id,
            "question_type": q.question_type,
            "content": content,
            "raw_content": q.raw_content or "",
            "options": q.options,
            "answer": q.answer or "",
            "analysis": q.analysis or "",
            "subject": {"id": q.subject_id, "label": subject_label} if subject_label else {"id": q.subject_id},
            "knowledge_points": q.knowledge_points or [],
            "primary_knowledge_point": _get_primary_kp(q),
            "image_urls": q.image_url or [],
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
        "total_count": len(questions_data),
        "skip_count": skip_count,
        "skip_reasons": skip_reasons if skip_reasons else None,
    }


def _extract_stem_text(content: dict, raw_content: str | None) -> str:
    """Return the best available textual stem without inventing content."""
    direct = content.get("stem") or content.get("text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    segment_texts: list[str] = []
    segments = content.get("segments")
    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            if segment.get("type", "text") == "text":
                text = segment.get("text")
                if isinstance(text, str) and text.strip():
                    segment_texts.append(text.strip())
            elif segment.get("type") == "newline" and segment_texts:
                segment_texts.append("\n")
    segment_stem = "".join(segment_texts).strip()
    if segment_stem:
        return segment_stem

    if isinstance(raw_content, str) and raw_content.strip():
        return raw_content.strip()
    return ""


def _has_stem_image(content: dict, image_urls: list | None) -> bool:
    if isinstance(image_urls, list) and any(bool(url) for url in image_urls):
        return True
    segments = content.get("segments")
    if not isinstance(segments, list):
        return False
    image_types = {"image", "code_image", "math_image", "table_image"}
    return any(
        isinstance(segment, dict)
        and segment.get("type") in image_types
        and bool(segment.get("url"))
        for segment in segments
    )


def _get_subject_label(q):
    """Get subject display name."""
    try:
        if q.subject_ref:
            return q.subject_ref.name
    except Exception:
        pass
    return None


def _get_primary_kp(q):
    """Return the first knowledge point."""
    if q.knowledge_points and len(q.knowledge_points) > 0:
        return str(q.knowledge_points[0])
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
