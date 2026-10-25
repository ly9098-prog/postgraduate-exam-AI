"""Helpers for the atomic practice batch submission flow.

These functions preserve the exact validation, grading, and response-building
rules previously inlined in ``practice_service.batch_submit_answers``. They are
intentionally pure with respect to database writes; the service owns the
transaction boundary.
"""

from __future__ import annotations

from typing import Any

from app.services.practice.normalization import (
    normalize_answer_used_time,
    normalize_practice_request_id,
)
from app.utils.answer_normalizer import (
    extract_multi_blank_slot_ids,
    is_answer_correct,
)

__all__ = [
    "validate_batch_submission_inputs",
    "evaluate_batch_answers",
    "build_session_consistency_error",
    "validate_answer_duration",
    "build_response_by_question",
]


def validate_batch_submission_inputs(
    *,
    answers: list[dict],
    skipped_question_ids: list[int],
    max_questions: int,
) -> tuple[list[int], list[int], list[int]]:
    """Validate answer/skipped lists and return normalized id groups."""
    answer_question_ids = [int(a["question_id"]) for a in answers]
    if len(answer_question_ids) != len(set(answer_question_ids)):
        raise ValueError("answers 中存在重复 question_id")
    skipped_ids = [int(qid) for qid in skipped_question_ids]
    if len(skipped_ids) != len(set(skipped_ids)):
        raise ValueError("skipped_question_ids 中存在重复 question_id")
    overlap = set(answer_question_ids) & set(skipped_ids)
    if overlap:
        raise ValueError(f"题目不能同时提交答案并标记跳过: {sorted(overlap)}")
    all_question_ids = answer_question_ids + skipped_ids
    if not all_question_ids:
        raise ValueError("practice batch 至少需要包含 1 道题")
    if len(all_question_ids) > max_questions:
        raise ValueError(f"单次练习最多允许 {max_questions} 题")
    return answer_question_ids, skipped_ids, all_question_ids


def evaluate_batch_answers(
    *,
    answers: list[dict],
    questions: dict[int, Any],
) -> tuple[list[tuple[Any, bool, str, int | None]], dict[int, str | None], int, int]:
    """Grade answers and return evaluated tuples, per-question request ids, and totals."""
    evaluated_answers: list[tuple[Any, bool, str, int | None]] = []
    answer_request_ids: dict[int, str | None] = {}
    total_correct = 0
    total_wrong = 0
    for answer in answers:
        q = questions[int(answer["question_id"])]
        user_answer = str(
            answer.get("user_answer", answer.get("answer", "")) or ""
        ).strip()
        if not user_answer:
            # Empty strings used to be graded as a normal wrong answer, which lets
            # stale/malformed clients inflate answered_count and wrong-question
            # statistics.  Unattempted questions belong in skipped_question_ids.
            raise ValueError(
                f"question_id={int(q.id)} 的 user_answer 不能为空；未作答题请放入 skipped_question_ids"
            )
        used_time = normalize_answer_used_time(answer.get("used_time"))
        answer_request_ids[int(q.id)] = normalize_practice_request_id(
            answer.get("request_id")
        )
        slot_ids = extract_multi_blank_slot_ids(
            getattr(q, "content", None),
            getattr(q, "options", None),
        )
        is_correct = is_answer_correct(
            user_answer,
            q.answer or "",
            q.question_type or "",
            slot_ids=slot_ids,
        )
        evaluated_answers.append((q, is_correct, user_answer, used_time))
        if is_correct:
            total_correct += 1
        else:
            total_wrong += 1
    return evaluated_answers, answer_request_ids, total_correct, total_wrong


def build_session_consistency_error(
    *,
    session_values: dict,
    request_id: str,
    total_question_count: int,
    batch_payload: dict,
) -> str | None:
    """Return a session consistency error message, or None if consistent."""
    if session_values.get("request_id") != request_id:
        return "session.request_id 归一化结果不一致"
    if int(session_values.get("question_count") or 0) != total_question_count:
        return "session.question_count 与本次批次题数不一致"
    # The batch token snapshots subject/mode semantics at issue time. Do not
    # re-resolve today's mutable subject tree during submit.
    if int(session_values.get("subject_id") or 0) != int(batch_payload.get("sid") or 0):
        return "session.subject_id 与练习批次不一致"
    if str(session_values.get("mode")) != str(batch_payload.get("mode")):
        return "session.mode 与练习批次不一致"
    return None


def validate_answer_duration(
    *,
    evaluated_answers: list[tuple[Any, bool, str, int | None]],
    duration_sec: int,
    tolerance_sec: int,
) -> str | None:
    """Return a duration error message, or None if all durations are valid."""
    answered_used_times = [
        int(used_time)
        for _q, _correct, _answer, used_time in evaluated_answers
        if used_time is not None
    ]
    max_allowed_answer_time = duration_sec + tolerance_sec
    if any(used_time > max_allowed_answer_time for used_time in answered_used_times):
        return "answers.used_time 不得明显超过本次练习总时长"
    if sum(answered_used_times) > max_allowed_answer_time:
        return "answers.used_time 合计不得明显超过本次练习总时长"
    return None


def build_response_by_question(
    *,
    records: list[tuple[Any, Any, bool, str, int | None]],
    skipped_questions: list[Any],
    revision_kps: dict[int, list[str]],
    wrong_question_ids: dict[int, int],
) -> dict[int, dict]:
    """Build the per-question response payload for a submitted batch."""
    response_by_question: dict[int, dict] = {}
    for record, q, is_correct, _user_answer, _used_time in records:
        response_by_question[int(q.id)] = {
            "record_id": int(record.id),
            "question_id": int(q.id),
            "is_correct": bool(is_correct),
            "correct_answer": q.answer,
            "status": "correct" if is_correct else "wrong",
            "analysis": q.analysis,
            "knowledge_points": revision_kps.get(int(q.question_version_id), []),
            "is_wrong_added": int(q.id) in wrong_question_ids,
            "wrong_question_id": wrong_question_ids.get(int(q.id)),
            "error_diagnosis": getattr(record, "_error_diagnosis_payload", None),
        }
    for q in skipped_questions:
        response_by_question[int(q.id)] = {
            "question_id": int(q.id),
            "is_correct": False,
            "correct_answer": q.answer,
            "status": "skipped",
            "analysis": q.analysis,
            "knowledge_points": revision_kps.get(int(q.question_version_id), []),
            "is_wrong_added": False,
            "wrong_question_id": None,
        }
    return response_by_question
