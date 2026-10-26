"""Ordered validation and grading before a signed practice batch is claimed.

The flow supplies live lookups so its existing validation hooks remain effective.
This module neither loads revisions nor claims or writes a session.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def validate_protocol(request: Any, *, ports: Callable[[str], Any]) -> Any:
    if not request.batch_token:
        raise ports("PracticeBatchTokenError")("batch_token 不能为空，请重新获取题目")
    if not request.session_meta:
        raise ports("PracticeBatchTokenError")("session 不能为空，请重新获取题目")
    if request.skipped_question_ids is None:
        raise ports("PracticeBatchTokenError")("skipped_question_ids 必须显式提交")
    if ports("len")(request.answers) > ports("PRACTICE_BATCH_MAX_QUESTIONS"):
        raise ports("ValueError")(
            f"answers 最多允许 {ports('PRACTICE_BATCH_MAX_QUESTIONS')} 题"
        )
    if ports("len")(request.skipped_question_ids) > ports(
        "PRACTICE_BATCH_MAX_QUESTIONS"
    ):
        raise ports("ValueError")(
            f"skipped_question_ids 最多允许 {ports('PRACTICE_BATCH_MAX_QUESTIONS')} 题"
        )
    _answer_ids, skipped_ids, all_ids = ports("validate_batch_submission_inputs")(
        answers=request.answers,
        skipped_question_ids=request.skipped_question_ids,
        max_questions=ports("PRACTICE_BATCH_MAX_QUESTIONS"),
    )
    payload_hash = ports("practice_submission_fingerprint")(
        answers=request.answers,
        skipped_question_ids=skipped_ids,
        session_meta=request.session_meta,
        batch_token=request.batch_token,
    )
    request_id = ports("normalize_practice_request_id")(
        request.session_meta.get("request_id")
    )
    if not request_id:
        raise ports("ValueError")("session.request_id 不能为空")
    return ports("BatchProtocol")(skipped_ids, all_ids, payload_hash, request_id)


def prepare_batch_submission(
    request: Any, protocol: Any, contract: Any, *, ports: Callable[[str], Any]
) -> Any:
    evaluated_answers, answer_request_ids, correct, wrong = ports(
        "evaluate_batch_answers"
    )(answers=request.answers, questions=contract.questions)
    skipped_questions = [contract.questions[qid] for qid in protocol.skipped_ids]
    session_values = ports("normalize_practice_session")(
        request.session_meta,
        user_id=request.user_id,
        answered_count=ports("len")(evaluated_answers),
        total_correct=correct,
        total_wrong=wrong,
    )
    ports("_validate_session_contract")(
        request=request,
        protocol=protocol,
        contract=contract,
        session_values=session_values,
        evaluated_answers=evaluated_answers,
    )
    scope_snapshot = ports("build_practice_session_scope")(
        contract.batch_payload.get("knowledge_context"),
        fallback_subject_id=ports("int")(session_values.get("subject_id") or 0),
    )
    ports("_validate_scope_subject")(scope_snapshot, session_values)
    return ports("PreparedBatchSubmission")(
        evaluated_answers=evaluated_answers,
        answer_request_ids=answer_request_ids,
        skipped_questions=skipped_questions,
        all_question_ids=protocol.all_question_ids,
        issued_revisions=contract.issued_revisions,
        issued_order=contract.issued_order,
        batch_payload=contract.batch_payload,
        session_values=session_values,
        scope_snapshot=scope_snapshot,
        payload_hash=protocol.payload_hash,
    )


def validate_session_contract(
    *,
    request: Any,
    protocol: Any,
    contract: Any,
    session_values: dict,
    evaluated_answers: list[tuple[Any, bool, str, int | None]],
    ports: Callable[[str], Any],
) -> None:
    consistency_error = ports("build_session_consistency_error")(
        session_values=session_values,
        request_id=protocol.request_id,
        total_question_count=ports("len")(protocol.all_question_ids),
        batch_payload=contract.batch_payload,
    )
    if consistency_error:
        if "request_id" in consistency_error or "question_count" in consistency_error:
            raise ports("ValueError")(consistency_error)
        raise ports("PracticeBatchTokenError")(consistency_error)
    duration_error = ports("validate_answer_duration")(
        evaluated_answers=evaluated_answers,
        duration_sec=ports("int")(session_values.get("duration_sec") or 0),
        tolerance_sec=ports("PRACTICE_ANSWER_DURATION_TOLERANCE_SEC"),
    )
    if duration_error:
        raise ports("ValueError")(duration_error)


def validated_revision_questions(
    issued_revisions: dict[int, int],
    revision_views: dict[int, Any],
    *,
    ports: Callable[[str], Any],
) -> dict[int, Any]:
    questions: dict[int, Any] = {}
    for question_id, revision_id in issued_revisions.items():
        view = revision_views.get(ports("int")(revision_id))
        if view is None or ports("int")(view.question_id) != ports("int")(question_id):
            raise ports("PracticeBatchTokenError")(
                "练习批次题目与 revision 绑定关系无效"
            )
        # Issued batches snapshot active revisions; later edits are not re-resolved.
        if not view.is_active:
            raise ports("PracticeBatchTokenError")("练习批次包含不可用题目 revision")
        questions[ports("int")(question_id)] = view
    return questions


def validate_scope_subject(
    scope_snapshot: dict | None, session_values: dict, *, ports: Callable[[str], Any]
) -> None:
    if scope_snapshot is None:
        return
    signed_subject_id = ports("int")(scope_snapshot.get("subject_id") or 0)
    if signed_subject_id and signed_subject_id != ports("int")(
        session_values.get("subject_id") or 0
    ):
        raise ports("PracticeBatchTokenError")("知识练习范围与练习科目不一致")


def build_practice_session(prepared: Any, *, ports: Callable[[str], Any]) -> Any:
    scope = prepared.scope_snapshot
    return ports("PracticeSession")(
        **prepared.session_values,
        submission_payload_hash=prepared.payload_hash,
        scope_type=ports("str")(scope["practice_mode"]) if scope is not None else None,
        scope_root_knowledge_point_id=ports("int")(scope["root_knowledge_point_id"])
        if scope is not None
        else None,
        scope_snapshot=scope,
    )
