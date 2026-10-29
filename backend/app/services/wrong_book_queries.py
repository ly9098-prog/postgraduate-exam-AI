"""Wrong-book current-question, scope and detail enrichment queries."""

from __future__ import annotations


async def _resolve_product_subject_ids(db, product_scope, *, ports):
    raw = ports("str")(product_scope or "").strip().lower()
    if not raw:
        return None
    if raw != "exam408":
        raise ports("HTTPException")(
            status_code=400, detail="product_scope must be exam408"
        )
    result = await db.execute(ports("select")(ports("Subject")))
    return ports("selected_408_subject_ids")(result.scalars().all())


async def _load_current_question_view(db, wq, *, ports):
    """Load the current question-bank projection for wrong-book display.

    ``WrongQuestion.question_version_id`` intentionally remains the immutable
    revision that produced the learner's latest wrong answer.  It is still used
    by review records/schedules for historical grading, but the wrong-book UI
    must follow the latest published question content after an admin correction.
    """
    result = await db.execute(
        ports("select")(ports("Question"))
        .options(ports("joinedload")(ports("Question").subject_ref))
        .where(ports("Question").id == wq.question_id)
    )
    question = result.scalar_one_or_none()
    if question is None:
        return (None, [])
    kp_map = await ports("load_question_kps")(db, [ports("int")(question.id)])
    return (question, kp_map.get(ports("int")(question.id), []))


async def _load_wrong_detail_view(db, user_id, wq_id, *, ports):
    """Load the wrong row and current question projection in one round trip.

    The detail endpoint previously queried ``wrong_questions`` and ``questions``
    serially before any enrichment work. This join preserves the same ownership
    and active-row semantics while removing one latency-sensitive DB hop.
    Knowledge-point names remain a separate batched lookup.
    """
    row = (
        await db.execute(
            ports("select")(ports("WrongQuestion"), ports("Question"))
            .outerjoin(
                ports("Question"),
                ports("Question").id == ports("WrongQuestion").question_id,
            )
            .options(ports("joinedload")(ports("Question").subject_ref))
            .where(
                ports("WrongQuestion").id == wq_id,
                ports("WrongQuestion").user_id == user_id,
                ports("WrongQuestion").is_active,
            )
        )
    ).one_or_none()
    if row is None:
        return (None, None, [])
    wq, question = row
    if question is None:
        return (wq, None, [])
    kp_map = await ports("load_question_kps")(db, [ports("int")(question.id)])
    return (wq, question, kp_map.get(ports("int")(question.id), []))


async def _enrich_single_wq_extra(db, user_id, wq, *, ports):
    """Compute detail enrichment in one database round trip.

    The wrong-detail screen is latency-sensitive and this data used to be read
    with two serial queries. Aggregate schedule fields so the query still
    returns one row when no active schedule exists, while the scalar count keeps
    the review-record lookup index friendly.
    """
    review_record_count_subquery = (
        ports("select")(ports("func").count(ports("ReviewRecord").id))
        .where(
            ports("ReviewRecord").question_id == wq.question_id,
            ports("ReviewRecord").question_version_id == wq.question_version_id,
            ports("ReviewRecord").user_id == user_id,
        )
        .scalar_subquery()
    )
    detail = (
        await db.execute(
            ports("select")(
                review_record_count_subquery.label("review_record_count"),
                ports("func")
                .max(ports("ReviewSchedule").repetitions)
                .label("repetitions"),
                ports("func")
                .max(ports("case")((ports("ReviewSchedule").mastered, 1), else_=0))
                .label("schedule_mastered"),
                ports("func")
                .max(ports("ReviewSchedule").next_review_at)
                .label("next_review_at"),
                ports("func")
                .max(ports("ReviewSchedule").last_reviewed_at)
                .label("last_reviewed_at"),
            ).where(
                ports("ReviewSchedule").question_id == wq.question_id,
                ports("ReviewSchedule").question_version_id == wq.question_version_id,
                ports("ReviewSchedule").user_id == user_id,
                ports("ReviewSchedule").is_active,
            )
        )
    ).one()
    return project_detail_review_fields(wq, detail, ports=ports)


def _validate_wrong_book_dates(date_from, date_to, *, ports):
    if date_from is not None and date_to is not None and (date_from > date_to):
        raise ports("HTTPException")(status_code=422, detail="开始日期不能晚于结束日期")


def project_detail_review_fields(wq, detail, *, ports):
    from app.services.review_scheduler import review_mastery_percent

    review_record_count = ports("int")(detail.review_record_count or 0)
    repetitions = ports("int")(detail.repetitions or 0)
    is_mastered = ports("bool")(wq.mastered or detail.schedule_mastered)
    mastery_percent = (
        1.0
        if is_mastered
        else ports("round")(review_mastery_percent(repetitions) / 100, 4)
    )
    return {
        "review_record_count": review_record_count,
        "next_review_at": detail.next_review_at if not is_mastered else None,
        "last_reviewed_at": detail.last_reviewed_at,
        "mastery_percent": mastery_percent,
    }
