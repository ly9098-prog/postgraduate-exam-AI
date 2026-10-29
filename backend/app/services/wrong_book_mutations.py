"""Wrong-book update, batch requests and cache invalidation."""

from __future__ import annotations


async def update_wrong(wq_id, data, db, current_user, *, ports):
    wq = await ports("svc").update_wrong(db, current_user.id, wq_id, data.error_type)
    if not wq:
        raise ports("HTTPException")(status_code=404, detail="错题记录不存在")
    await ports("cache").delete(f"wrong_questions:*:{current_user.id}*")
    await ports("cache").delete(f"stats:*:{current_user.id}*")
    question, knowledge_points = await ports("_load_current_question_view")(db, wq)
    extra = await ports("_enrich_single_wq_extra")(db, current_user.id, wq)
    return ports("enrich_wq")(wq, question, knowledge_points=knowledge_points, **extra)


async def batch_operate(data, db, current_user, *, ports):
    """批量操作错题本记录。id 去重后限制 1~100；非本人的记录静默跳过。"""
    result = await ports("svc").batch_operate(
        db, current_user.id, data.action.value, data.ids
    )
    if not result.get("success"):
        raise ports("HTTPException")(status_code=400, detail="批量操作失败")
    uid = current_user.id
    patterns = [
        f"wrong_questions:*:{uid}*",
        f"stats:*:{uid}*",
        f"review:*:{uid}*",
        f"stats:dashboard*:{uid}*",
    ]
    for p in patterns:
        await ports("cache").delete(p)
    return result
