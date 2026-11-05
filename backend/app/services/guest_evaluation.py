"""Read-only grading for account-free practice batches."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.question_type import QT_SUBJECTIVE
from app.schemas.guest import (
    GuestAnswerSubmit,
    GuestEvaluateResponse,
    GuestEvaluationItem,
)
from app.services.guest_practice import GuestPracticeBatch, GuestPracticeError
from app.services.practice.response_content import sanitize_text_field
from app.services.question_revision_service import load_revision_views
from app.utils.answer_normalizer import (
    extract_multi_blank_slot_ids,
    is_answer_correct,
)


def _answer_map(
    batch: GuestPracticeBatch, answers: list[GuestAnswerSubmit]
) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for answer in answers:
        question_id = int(answer.question_id)
        if question_id not in batch.revisions:
            raise GuestPracticeError("作答题目不在本次体验批次内")
        if question_id in mapping:
            raise GuestPracticeError("同一题目不能重复提交")
        mapping[question_id] = str(answer.user_answer or "").strip()
    return mapping


def _grade_one(view, user_answer: str) -> tuple[bool | None, bool, bool]:
    """Return (is_correct, reference_only, skipped) for one revision."""
    question_type = str(view.question_type or "")
    if not user_answer:
        return None, question_type == QT_SUBJECTIVE, True
    if question_type == QT_SUBJECTIVE:
        return None, True, False
    slot_ids = extract_multi_blank_slot_ids(view.content, view.options)
    correct = is_answer_correct(
        user_answer,
        str(view.answer or ""),
        question_type,
        slot_ids=slot_ids,
    )
    return correct, False, False


async def evaluate_guest_answers(
    db: AsyncSession,
    *,
    batch: GuestPracticeBatch,
    answers: list[GuestAnswerSubmit],
) -> GuestEvaluateResponse:
    mapping = _answer_map(batch, answers)
    views = await load_revision_views(db, batch.revisions.values())
    items: list[GuestEvaluationItem] = []
    objective_total = objective_correct = objective_incorrect = 0
    subjective_total = skipped_total = 0
    for question_id in batch.question_ids:
        revision_id = batch.revisions[question_id]
        view = views.get(revision_id)
        if view is None or int(view.question_id) != int(question_id):
            raise GuestPracticeError("体验题目版本已失效，请重新出题")
        user_answer = mapping.get(question_id, "")
        is_correct, reference_only, skipped = _grade_one(view, user_answer)
        if skipped:
            skipped_total += 1
        elif reference_only:
            subjective_total += 1
        else:
            objective_total += 1
            if is_correct:
                objective_correct += 1
            else:
                objective_incorrect += 1
        items.append(
            GuestEvaluationItem(
                question_id=int(question_id),
                question_type=str(view.question_type or ""),
                is_correct=is_correct,
                user_answer=user_answer,
                correct_answer=sanitize_text_field(str(view.answer or "")) or "",
                analysis=sanitize_text_field(view.analysis),
                reference_only=reference_only,
            )
        )
    return GuestEvaluateResponse(
        items=items,
        total=len(items),
        objective_total=objective_total,
        objective_correct=objective_correct,
        objective_incorrect=objective_incorrect,
        subjective_total=subjective_total,
        skipped_total=skipped_total,
    )
