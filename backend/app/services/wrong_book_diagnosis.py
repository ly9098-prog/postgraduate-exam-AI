"""Wrong-book diagnosis read, confirmation and suggestion requests."""

from __future__ import annotations


async def get_wrong_error_diagnosis(wq_id, db, current_user, *, ports):
    wq = await ports("svc").get_by_id(db, current_user.id, wq_id)
    if not wq:
        raise ports("HTTPException")(status_code=404, detail="错题记录不存在")
    row = await ports("error_diagnosis_service").get_latest_diagnosis(
        db, current_user.id, wq_id
    )
    if row is None:
        row = await ports("error_diagnosis_service").ensure_legacy_diagnosis(db, wq)
        await db.commit()
        await db.refresh(row)
    return ports("error_diagnosis_service").serialize_diagnosis(row)


async def confirm_wrong_error_diagnosis(wq_id, data, db, current_user, *, ports):
    row = await ports("error_diagnosis_service").confirm_diagnosis(
        db,
        user_id=current_user.id,
        wrong_question_id=wq_id,
        primary_type=data.primary_type,
        secondary_types=data.secondary_types,
        diagnosis_id=data.diagnosis_id,
    )
    if row is None:
        raise ports("HTTPException")(status_code=404, detail="错题记录不存在")
    for pattern in (
        f"wrong_questions:*:{current_user.id}*",
        f"stats:*:{current_user.id}*",
        f"stats:dashboard*:{current_user.id}*",
    ):
        await ports("cache").delete(pattern)
    return ports("error_diagnosis_service").serialize_diagnosis(row)


async def suggest_wrong_error_diagnosis(wq_id, db, current_user, *, ports):
    row, queued = await ports("error_diagnosis_service").request_ai_suggestion(
        db, user_id=current_user.id, wrong_question_id=wq_id
    )
    if row is None:
        raise ports("HTTPException")(status_code=404, detail="错题记录不存在")
    return {
        "queued": queued,
        "diagnosis": ports("error_diagnosis_service").serialize_diagnosis(row),
    }
