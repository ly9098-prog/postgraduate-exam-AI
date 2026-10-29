"""Practice submission diagnostics, error mapping and cache response lifecycle."""

from __future__ import annotations


async def batch_submit(data, x_trace_id, db, current_user, *, ports):
    trace_id = ports("str")(
        ports("get_log_context")().get("trace_id")
        or ports("normalize_trace_id")(x_trace_id)
    )
    ports("debug_log")(
        trace_id,
        "SUBMIT",
        {
            "endpoint": "practice/batch-submit",
            "answer_count": ports("len")(data.answers),
        },
    )
    ports("save_debug_snapshot")(
        trace_id,
        "submit_before",
        {"question_ids": [answer.question_id for answer in data.answers]},
    )
    result = await _submit_answers(data, db, current_user, trace_id, ports=ports)
    await ports("cache").delete(f"practice:stats:{current_user.id}:*")
    await ports("cache").delete(f"stats:*:{current_user.id}*")
    await ports("cache").delete(f"review:*:{current_user.id}*")
    ports("save_debug_snapshot")(
        trace_id,
        "submit_after",
        {
            "total_correct": result["total_correct"],
            "total_wrong": result["total_wrong"],
            "total_skipped": result.get("total_skipped", 0),
            "result_count": ports("len")(result["results"]),
        },
    )
    return ports("BatchSubmitResponse")(
        results=[ports("AnswerResult")(**r) for r in result["results"]],
        total_correct=result["total_correct"],
        total_wrong=result["total_wrong"],
        total_skipped=result.get("total_skipped", 0),
        trace_id=trace_id,
        knowledge_session=result.get("knowledge_session"),
    )


async def _submit_answers(data, db, current_user, trace_id, *, ports):
    try:
        result = await ports("svc").batch_submit_answers(
            db=db,
            user_id=current_user.id,
            answers=[a.model_dump() for a in data.answers],
            session_meta=data.session.model_dump()
            if data.session is not None
            else None,
            skipped_question_ids=data.skipped_question_ids,
            batch_token=data.batch_token,
        )
    except ports("svc").PracticeBatchTokenError as e:
        ports("logger").warning(
            "practice submit batch token rejected uid=%s trace_id=%s: %s",
            current_user.id,
            trace_id,
            e,
        )
        raise ports("HTTPException")(
            status_code=400,
            detail={"error_code": "PRACTICE_BATCH_INVALID", "retryable": False},
        )
    except ports("svc").PracticeSubmissionConflictError as e:
        ports("logger").warning(
            "practice submit idempotency conflict uid=%s trace_id=%s: %s",
            current_user.id,
            trace_id,
            e,
        )
        raise ports("HTTPException")(
            status_code=409,
            detail={"error_code": "PRACTICE_SUBMISSION_CONFLICT", "retryable": False},
        )
    except ports("ValueError") as e:
        ports("logger").warning(
            "practice submit payload rejected uid=%s trace_id=%s: %s",
            current_user.id,
            trace_id,
            e,
        )
        raise ports("HTTPException")(
            status_code=400,
            detail={"error_code": "PRACTICE_PAYLOAD_INVALID", "retryable": False},
        )
    return result
