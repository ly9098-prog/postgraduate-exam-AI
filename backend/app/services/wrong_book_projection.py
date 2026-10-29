"""Wrong-book AI metadata and response projection."""

from __future__ import annotations


def enrich_wq(ports, /, wq, question, knowledge_points, **extra):
    ai_analysis, raw_generated_at, ai_status = resolve_analysis_projection(
        wq, extra, ports=ports
    )
    # A deleted question keeps knowledge_points=None; a live empty one uses [].
    if question is None:
        kps = None
    else:
        kps = knowledge_points if knowledge_points is not None else []
    return build_wrong_response(
        wq, question, extra, ai_analysis, raw_generated_at, ai_status, kps, ports=ports
    )


def resolve_analysis_projection(wq, extra, *, ports):
    ai_analysis = (
        extra["ai_analysis_override"]
        if "ai_analysis_override" in extra
        else wq.ai_analysis
    )
    raw_ai_analysis = (
        wq.ai_analysis if ports("isinstance")(wq.ai_analysis, ports("dict")) else {}
    )
    raw_ai_meta = (
        raw_ai_analysis.get("_meta")
        if ports("isinstance")(raw_ai_analysis, ports("dict"))
        else None
    )
    raw_generated_at = (
        ports("str")(raw_ai_meta.get("generated_at") or "").strip()
        if ports("isinstance")(raw_ai_meta, ports("dict"))
        else ""
    )
    ai_status = extra.get("ai_analysis_status_override")
    if ai_status is None:
        ai_status = (
            "ready"
            if ports("isinstance")(ai_analysis, ports("dict")) and ai_analysis
            else "empty"
        )
    return (ai_analysis, raw_generated_at, ai_status)


def build_wrong_response(
    wq, question, extra, ai_analysis, raw_generated_at, ai_status, kps, *, ports
):
    return ports("WrongQuestionResponse")(
        id=wq.id,
        question_id=wq.question_id,
        wrong_answer=wq.wrong_answer,
        error_type=wq.error_type,
        review_count=wq.review_count,
        created_at=wq.created_at,
        updated_at=wq.updated_at,
        subject_id=question.subject_id if question else None,
        subject_code=question.subject_ref.code
        if question and question.subject_ref
        else None,
        subject_name=question.subject_ref.name
        if question and question.subject_ref
        else None,
        question_type=question.question_type if question else None,
        content=ports("_sanitize_content")(question.content) if question else None,
        options=ports("_sanitize_options")(question.options) if question else None,
        answer=question.answer if question else None,
        analysis=question.analysis if question else None,
        knowledge_points=kps,
        image_url=question.image_url if question else None,
        ai_analysis=ai_analysis,
        ai_analysis_status=ai_status,
        ai_analysis_generated_at=raw_generated_at or None,
        wrong_count=extra.get("wrong_count", wq.review_count or 0),
        review_record_count=extra.get("review_record_count", 0),
        mastery_percent=extra.get("mastery_percent", 0.0),
        is_mastered=extra.get("is_mastered", wq.mastered or False),
        next_review_at=extra.get("next_review_at", None),
        last_reviewed_at=extra.get("last_reviewed_at", None),
        last_wrong_at=extra.get("last_wrong_at", wq.last_review_at),
        error_diagnosis=extra.get("error_diagnosis"),
    )
