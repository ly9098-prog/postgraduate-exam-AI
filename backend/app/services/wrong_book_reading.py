"""Wrong-book list, task-flow and cached-analysis detail requests."""

from __future__ import annotations


async def list_wrong(
    subject_id,
    error_type,
    topic,
    page,
    page_size,
    product_scope,
    date_from,
    date_to,
    db,
    current_user,
    *,
    ports,
):
    ports("_validate_wrong_book_dates")(date_from, date_to)
    allowed_subject_ids = await ports("_resolve_product_subject_ids")(db, product_scope)
    items, total = await ports("svc").list_wrong_enriched(
        db,
        current_user.id,
        subject_id,
        error_type,
        topic,
        page,
        page_size,
        allowed_subject_ids=allowed_subject_ids,
        date_from=date_from,
        date_to=date_to,
    )
    for item in items:
        item["content"] = ports("_sanitize_content")(item.get("content"))
        item["options"] = ports("_sanitize_options")(item.get("options"))
    return ports("paginated_response")(
        items=items, total=total, page=page, page_size=page_size
    )


async def get_task_flow(
    subject_id,
    error_type,
    topic,
    preview_size,
    product_scope,
    date_from,
    date_to,
    db,
    current_user,
    *,
    ports,
):
    """错题任务流分组：今日应复习 → 高频错题 → 最近新增 → 待巩固 → 已掌握."""
    ports("_validate_wrong_book_dates")(date_from, date_to)
    allowed_subject_ids = await ports("_resolve_product_subject_ids")(db, product_scope)
    result = await ports("svc").get_task_flow(
        db,
        current_user.id,
        subject_id,
        error_type,
        topic,
        preview_size,
        allowed_subject_ids=allowed_subject_ids,
        date_from=date_from,
        date_to=date_to,
    )
    for group in result.get("groups", []):
        for item in group.get("items", []):
            item["content"] = ports("_sanitize_content")(item.get("content"))
            item["options"] = ports("_sanitize_options")(item.get("options"))
    return result


async def get_wrong(wq_id, db, current_user, *, ports):
    """获取单条错题详情（含关联题目信息）"""
    wq, question, knowledge_points = await ports("_load_wrong_detail_view")(
        db, current_user.id, wq_id
    )
    if not wq:
        raise ports("HTTPException")(status_code=404, detail="错题记录不存在")
    extra = await ports("_enrich_single_wq_extra")(db, current_user.id, wq)
    diagnosis = await ports("error_diagnosis_service").get_latest_diagnosis(
        db, current_user.id, wq.id
    )
    if diagnosis is not None:
        extra["error_diagnosis"] = ports("error_diagnosis_service").serialize_diagnosis(
            diagnosis
        )
    if question is not None:
        from app.services import ai_service

        cache_state = await ai_service.evaluate_cached_error_analysis(
            db, wq, question, knowledge_points=knowledge_points
        )
        extra["ai_analysis_override"] = cache_state.get("analysis")
        extra["ai_analysis_status_override"] = cache_state.get("status")
    return ports("enrich_wq")(wq, question, knowledge_points=knowledge_points, **extra)
