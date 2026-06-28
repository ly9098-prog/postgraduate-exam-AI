import logging
from datetime import datetime
from math import ceil
from uuid import uuid4

from fastapi import Request
from sqlalchemy import String, case, delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow
from app.core.admin_security import AdminPrincipal
from app.core.cache import cache
from app.features import question_pipeline
from app.models.question_import import QuestionImport
from app.schemas.admin_imports import (
    AdminImportBatchDetail,
    AdminImportEnrichResponse,
    AdminImportQuestionItem,
    AdminImportQuestionItemBrief,
    AdminImportQuestionUpdateRequest,
)
from app.services.admin_ai_settings_service import ensure_ai_parse_allowed
from app.services.admin_audit_service import write_admin_audit

logger = logging.getLogger(__name__)

_TASK_TTL_SECONDS = 86400


def derive_import_risk(
    ai_metadata: dict | None,
    *,
    ai_answer_flag: bool | None = None,
    parsed_answer: str | None = None,
) -> dict:
    """从导入题目元数据推导风险等级。

    Returns:
        {"risk_flags": [...], "risk_level": "high"|"medium"|"low", "risk_reasons": [...]}
    """
    risk_flags: list[str] = []
    meta = ai_metadata or {}

    # 1. 从 ai_metadata.risk_flags 提取已有的风险标记
    meta_risk_flags = meta.get("risk_flags")
    if isinstance(meta_risk_flags, list):
        risk_flags.extend(meta_risk_flags)

    # 2. 答案 AI 生成
    if ai_answer_flag:
        risk_flags.append("answer_ai_generated")

    # 3. 答案缺失（pending 状态且无答案）
    has_answer = bool(parsed_answer and parsed_answer.strip())
    if not has_answer:
        risk_flags.append("answer_missing")

    # 4. AI 修复/补全来源
    ai_source = meta.get("ai_source") or ""
    if ai_source in ("repair", "complete", "enrich"):
        flag = f"ai_{ai_source}"
        if flag not in risk_flags:
            risk_flags.append(flag)

    # 5. 置信度过低
    confidence = meta.get("confidence") or meta.get("confidence_score")
    if confidence is not None and isinstance(confidence, (int, float)):
        if confidence < 0.5:
            risk_flags.append("low_confidence")

    risk_reasons = _build_risk_reasons(risk_flags)
    risk_level = _compute_risk_level(risk_flags)

    return {
        "risk_flags": risk_flags,
        "risk_level": risk_level,
        "risk_reasons": risk_reasons,
    }


def _compute_risk_level(risk_flags: list[str]) -> str:
    flag_set = set(risk_flags)
    high_flags = {
        "answer_ai_generated", "code_uncertain", "formula_uncertain",
        "options_anomaly", "answer_missing", "ai_major_edit",
        "math_image_crop_failed", "math_image_upload_failed",
        "source_image_upload_failed",
        "table_low_confidence", "complex_formula_requires_review",
    }
    medium_flags = {
        "ai_repair", "ai_complete", "ai_enrich",
        "low_confidence", "contains_code", "contains_formula",
        "answer_uncertain",
        "math_region_detected", "math_image_attached",
        "table_detected", "table_requires_review",
        "source_region_available",
    }
    if flag_set & high_flags:
        return "high"
    if flag_set & medium_flags:
        return "medium"
    return "low"


def _build_risk_reasons(risk_flags: list[str]) -> list[str]:
    flag_to_reason = {
        "answer_ai_generated": "答案由 AI 补全，请核对原题",
        "code_uncertain": "代码部分 AI 无法确认，请人工核对",
        "formula_uncertain": "公式可能识别不准确，请人工核对",
        "options_anomaly": "选项数量异常，请检查",
        "answer_missing": "答案缺失，需人工确认",
        "ai_major_edit": "AI 大幅修改了题目内容，请仔细核对",
        "ai_repair": "AI 修复了题目结构",
        "ai_complete": "AI 补全了缺失字段",
        "ai_enrich": "AI 丰富了题目信息",
        "low_confidence": "OCR 置信度偏低，请仔细核对",
        "contains_code": "题目包含代码，请注意缩进和符号",
        "contains_formula": "题目包含数学公式，请核对",
        "answer_uncertain": "答案不确定，需人工确认",
        "non_question_like": "内容可能不是标准题目格式",
        "no_exercise_regions": "未检测到习题区域",
        "ocr_garbled_code": "检测到 OCR 乱码",
        # P1: 公式截图与表格风险
        "math_region_detected": "检测到数学公式区域",
        "math_low_confidence": "公式 OCR 置信度偏低，请核对",
        "complex_formula_requires_review": "检测到复杂公式，需人工核对",
        "math_image_attached": "已生成公式截图",
        "math_image_crop_failed": "公式截图裁剪失败",
        "math_image_upload_failed": "公式截图上传失败",
        "table_detected": "检测到表格内容",
        "table_requires_review": "表格内容需核对",
        "table_low_confidence": "表格置信度偏低，请核对",
        "source_region_available": "原题区域截图可用",
        "source_image_upload_failed": "原题截图上传失败",
    }
    reasons: list[str] = []
    seen: set[str] = set()
    for flag in risk_flags:
        reason = flag_to_reason.get(flag)
        if reason and reason not in seen:
            reasons.append(reason)
            seen.add(reason)
    return reasons


async def list_import_batches(
    db: AsyncSession,
    page: int,
    page_size: int,
    status: str | None = None,
    source_type: str | None = None,
    keyword: str | None = None,
) -> tuple[list[dict], int]:
    conditions = _batch_conditions(status, source_type, keyword)
    total_query = select(func.count()).select_from(select(QuestionImport.batch_id).where(*conditions).group_by(QuestionImport.batch_id).subquery())
    total = await db.scalar(total_query)

    result = await db.execute(
        _batch_summary_query(conditions)
        .order_by(desc("updated_at"), desc("created_at"), QuestionImport.batch_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [_batch_row_to_dict(row) for row in result.all()], int(total or 0)


async def get_import_batch_detail(
    db: AsyncSession,
    batch_id: str,
    page: int,
    page_size: int,
    status: str | None = None,
) -> AdminImportBatchDetail:
    batch_conditions = [QuestionImport.batch_id == batch_id]
    summary_result = await db.execute(_batch_summary_query(batch_conditions))
    summary_row = summary_result.first()
    if not summary_row:
        raise ValueError("导入批次不存在")

    item_conditions = [QuestionImport.batch_id == batch_id]
    if status:
        item_conditions.append(QuestionImport.status == status)
    total = await db.scalar(select(func.count()).select_from(QuestionImport).where(*item_conditions))
    item_result = await db.execute(
        select(*_LIST_COLUMNS)
        .where(*item_conditions)
        .order_by(QuestionImport.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    item_rows = item_result.mappings().all()
    items = [_brief_from_row(row) for row in item_rows]
    summary = _batch_row_to_dict(summary_row)
    return AdminImportBatchDetail(
        **summary,
        items=items,
        page=page,
        page_size=page_size,
        total_pages=max(ceil(int(total or 0) / page_size), 1) if total else 0,
    )


def _apply_risk_to_item(item: AdminImportQuestionItem) -> AdminImportQuestionItem:
    """对单个 item 注入风险字段（risk_flags / risk_level / risk_reasons）。"""
    risk = derive_import_risk(
        item.ai_metadata,
        ai_answer_flag=item.ai_answer_flag,
        parsed_answer=item.parsed_answer,
    )
    # 用 model_config 允许额外字段
    item.risk_flags = risk["risk_flags"]
    item.risk_level = risk["risk_level"]
    item.risk_reasons = risk["risk_reasons"]
    return item


_LIST_COLUMNS = (
    QuestionImport.id,
    QuestionImport.batch_id,
    QuestionImport.source_type,
    QuestionImport.source_file,
    QuestionImport.subject,
    QuestionImport.question_type,
    QuestionImport.parsed_answer,
    QuestionImport.question_hash,
    QuestionImport.duplicate_status,
    QuestionImport.duplicate_of_question_id,
    QuestionImport.duplicate_of_import_id,
    QuestionImport.status,
    QuestionImport.review_note,
    QuestionImport.question_id,
    QuestionImport.reject_reason,
    QuestionImport.reviewed_by,
    QuestionImport.reviewed_at,
    QuestionImport.ai_generated,
    QuestionImport.ai_source,
    QuestionImport.ai_confidence,
    QuestionImport.ai_metadata,
    QuestionImport.ai_reviewed_at,
    QuestionImport.ai_answer_flag,
    QuestionImport.created_at,
    QuestionImport.updated_at,
    func.substr(
        func.coalesce(
            QuestionImport.parsed_content['text'].as_string(),
            QuestionImport.parsed_content.cast(String),
        ), 1, 160
    ).label("content_preview"),
)


def _brief_from_row(row) -> AdminImportQuestionItemBrief:
    """Convert a row mapping to AdminImportQuestionItemBrief with risk fields."""
    item = AdminImportQuestionItemBrief.model_validate(row)
    risk = derive_import_risk(
        item.ai_metadata,
        ai_answer_flag=item.ai_answer_flag,
        parsed_answer=item.parsed_answer,
    )
    item.risk_flags = risk["risk_flags"]
    item.risk_level = risk["risk_level"]
    item.risk_reasons = risk["risk_reasons"]
    return item


async def list_review_queue(
    db: AsyncSession,
    page: int,
    page_size: int,
    status: str | None = "pending",
    batch_id: str | None = None,
    subject: str | None = None,
    source_type: str | None = None,
    keyword: str | None = None,
    risk_level: str | None = None,
) -> tuple[list[AdminImportQuestionItemBrief], int]:
    conditions = _question_conditions(status, batch_id, subject, source_type, keyword)
    total = await db.scalar(select(func.count()).select_from(QuestionImport).where(*conditions))
    result = await db.execute(
        select(*_LIST_COLUMNS)
        .where(*conditions)
        .order_by(QuestionImport.created_at.desc(), QuestionImport.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.mappings().all()
    items = [_brief_from_row(row) for row in rows]

    # 风险等级过滤（内存过滤，因为 risk_level 是动态计算的）
    if risk_level:
        items = [item for item in items if item.risk_level == risk_level]

    return items, int(total or 0)


async def update_import_question(
    db: AsyncSession,
    import_id: int,
    data: AdminImportQuestionUpdateRequest,
) -> AdminImportQuestionItem:
    qi = await _get_import_question(db, import_id)
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可编辑")

    payload = data.model_dump(exclude_none=True)
    if "stem" in payload:
        from app.services.pdf_text_normalizer import deduplicate_repeated_text
        content = dict(qi.parsed_content or {})
        content["text"] = deduplicate_repeated_text(payload.pop("stem").strip())
        qi.parsed_content = content
    if "options" in payload:
        options = payload.pop("options")
        qi.parsed_options = {str(item.get("key") or item.get("label")): item.get("text") or item.get("value") for item in options if isinstance(item, dict)} if isinstance(options, list) else options
    if "answer" in payload:
        qi.parsed_answer = payload.pop("answer")
        qi.ai_answer_flag = False
    if "analysis" in payload:
        qi.parsed_analysis = payload.pop("analysis")

    for field in (
        "subject",
        "question_type",
        "raw_data",
        "parsed_content",
        "parsed_options",
        "parsed_answer",
        "parsed_analysis",
        "review_note",
    ):
        if field in payload:
            setattr(qi, field, payload[field])
    await db.flush()
    await db.refresh(qi)
    return AdminImportQuestionItem.model_validate(qi)


async def approve_import_question(db: AsyncSession, import_id: int, operator_id: int) -> AdminImportQuestionItem:
    qi = await _get_import_question(db, import_id)
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可重复审核")

    qi.status = "approved"
    qi.reject_reason = None
    qi.reviewed_by = operator_id
    qi.reviewed_at = utcnow()

    # 审核即发布：写入 questions 正式题库
    from app.features.question_publish_service import publish_single_question

    pub_result = await publish_single_question(db, qi)
    if pub_result["status"] == "duplicate":
        qi.status = "published"
        qi.question_id = pub_result["question_id"]
    elif pub_result["status"] == "failed":
        logger.warning(
            "Auto-publish failed for import %d: %s (rolling back approval)",
            import_id, pub_result.get("reason"),
        )
        qi.status = "pending"  # 回滚状态，保留在审核队列等待修复后重试
        qi.reviewed_by = None
        qi.reviewed_at = None
        raise ValueError(
            f"题目数据不完整，无法发布到题库：{pub_result.get('reason', '未知错误')}"
        )

    await db.flush()
    await db.refresh(qi)
    return AdminImportQuestionItem.model_validate(qi)


async def batch_complete_import_questions(
    db: AsyncSession,
    import_ids: list[int],
    fields: list[str],
    strategy: str,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> dict:
    """批量 AI 补全导入题目。"""
    if len(import_ids) > 50:
        raise ValueError("单次批量补全最多支持 50 条")
    if not fields:
        raise ValueError("请选择至少一个补全字段")
    if strategy not in ("fill_empty", "force_overwrite"):
        raise ValueError("strategy 仅支持 fill_empty 或 force_overwrite")

    await ensure_ai_parse_allowed(db, operator, request)
    from app.services.admin_ai_settings_service import is_super_admin
    _skip_budget = await is_super_admin(db, operator)
    result = await question_pipeline.batch_complete_questions(
        db, operator.id, import_ids, fields, strategy, skip_budget_check=_skip_budget,
    )

    await write_admin_audit(
        db,
        operator,
        "import.batch_complete",
        "question_import",
        f"ids={import_ids}",
        severity="important",
        detail={
            "import_ids": import_ids,
            "fields": fields,
            "strategy": strategy,
            "result": {k: result[k] for k in ("total", "succeeded", "failed", "skipped")},
        },
        request=request,
    )
    await db.commit()
    return result


async def reject_import_question(db: AsyncSession, import_id: int, operator_id: int, reason: str | None = None) -> AdminImportQuestionItem:
    qi = await _get_import_question(db, import_id)
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可驳回")
    qi.status = "rejected"
    qi.reject_reason = reason
    qi.review_note = reason or qi.review_note
    qi.reviewed_by = operator_id
    qi.reviewed_at = utcnow()
    await db.flush()
    await db.refresh(qi)
    return AdminImportQuestionItem.model_validate(qi)


async def approve_import_batch(db: AsyncSession, batch_id: str, operator_id: int) -> int:
    records = await _get_batch_records(db, batch_id, statuses={"pending", "rejected"})
    now = utcnow()
    from app.features.question_publish_service import publish_single_question

    count = 0
    for qi in records:
        if qi.question_id is None:
            qi.status = "approved"
            qi.reject_reason = None
            qi.reviewed_by = operator_id
            qi.reviewed_at = now

            # 批量审核即批量发布
            try:
                pub = await publish_single_question(db, qi)
                if pub["status"] == "duplicate":
                    qi.status = "published"
                    qi.question_id = pub["question_id"]
                elif pub["status"] == "failed":
                    logger.warning(
                        "Batch auto-publish failed for import %d: %s (skipped)",
                        qi.id, pub.get("reason"),
                    )
                    qi.status = "pending"  # 回滚，留在审核队列
                    qi.reviewed_by = None
                    qi.reviewed_at = None
            except Exception as exc:
                logger.warning(
                    "Batch auto-publish error for import %d: %s", qi.id, exc,
                )
                qi.status = "pending"  # 异常也回滚
                qi.reviewed_by = None
                qi.reviewed_at = None

            count += 1

    await db.flush()
    return count


async def approve_low_risk_questions(db: AsyncSession, batch_id: str, operator_id: int) -> dict:
    """批量通过低风险题目：只通过 risk_level == "low" 且无高风险标记的待审核题。

    Returns:
        {"affected_count": int, "skipped_count": int, "skipped_reasons": list[str]}
    """
    from app.features.question_publish_service import publish_single_question

    records = await _get_batch_records(db, batch_id, statuses={"pending"})
    now = utcnow()

    affected = 0
    skipped = 0
    skipped_reasons: list[str] = []

    for qi in records:
        risk = derive_import_risk(
            qi.ai_metadata,
            ai_answer_flag=qi.ai_answer_flag,
            parsed_answer=qi.parsed_answer,
        )
        rl = risk["risk_level"]
        flags = risk["risk_flags"]

        # 低风险条件
        is_low_risk = (
            rl == "low"
            and not qi.ai_answer_flag
            and bool(qi.parsed_answer and qi.parsed_answer.strip())
            and "math_low_confidence" not in flags
            and "complex_formula_requires_review" not in flags
            and "table_low_confidence" not in flags
            and "code_symbol_risk" not in flags
            and "option_structure_corruption" not in flags
        )

        if not is_low_risk:
            skipped += 1
            if rl == "high":
                skipped_reasons.append(f"#{qi.id}: 高风险")
            elif qi.ai_answer_flag:
                skipped_reasons.append(f"#{qi.id}: AI 答案")
            elif not qi.parsed_answer or not qi.parsed_answer.strip():
                skipped_reasons.append(f"#{qi.id}: 答案缺失")
            else:
                skipped_reasons.append(f"#{qi.id}: 需检查")
            continue

        if qi.question_id is None:
            qi.status = "approved"
            qi.reject_reason = None
            qi.reviewed_by = operator_id
            qi.reviewed_at = now

            try:
                pub = await publish_single_question(db, qi)
                if pub["status"] == "duplicate":
                    qi.status = "published"
                    qi.question_id = pub["question_id"]
                elif pub["status"] == "failed":
                    logger.warning(
                        "Low-risk approve publish failed for import %d: %s (rolled back)",
                        qi.id, pub.get("reason"),
                    )
                    qi.status = "pending"
                    qi.reviewed_by = None
                    qi.reviewed_at = None
                    skipped += 1
                    skipped_reasons.append(f"#{qi.id}: 发布失败({pub.get('reason', '未知')})")
                    continue
            except Exception as exc:
                logger.warning(
                    "Low-risk approve publish error for import %d: %s", qi.id, exc,
                )
                qi.status = "pending"
                qi.reviewed_by = None
                qi.reviewed_at = None
                skipped += 1
                affected -= 1 if affected > 0 else 0
                skipped_reasons.append(f"#{qi.id}: 发布异常({exc})")
                continue

            affected += 1

    await db.flush()

    # 最多返回 20 条跳过原因，避免响应体过大
    if len(skipped_reasons) > 20:
        skipped_reasons = skipped_reasons[:20]
        skipped_reasons.append(f"... 及其他 {skipped - 20} 条跳过原因")

    return {
        "affected_count": affected,
        "skipped_count": skipped,
        "skipped_reasons": skipped_reasons,
    }


async def reject_import_batch(db: AsyncSession, batch_id: str, operator_id: int, reason: str | None = None) -> int:
    records = await _get_batch_records(db, batch_id, statuses={"pending", "approved"})
    now = utcnow()
    for qi in records:
        if qi.question_id is None:
            qi.status = "rejected"
            qi.reject_reason = reason
            qi.review_note = reason or qi.review_note
            qi.reviewed_by = operator_id
            qi.reviewed_at = now
    await db.flush()
    return len(records)


async def delete_import_question(db: AsyncSession, import_id: int) -> int:
    qi = await _get_import_question(db, import_id)
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可删除")
    await db.delete(qi)
    await db.flush()
    return 1


async def delete_import_batch(db: AsyncSession, batch_id: str) -> int:
    records = await _get_batch_records(db, batch_id)
    if any(qi.status == "published" or qi.question_id is not None for qi in records):
        raise ValueError("已发布批次不可删除")
    result = await db.execute(delete(QuestionImport).where(QuestionImport.batch_id == batch_id))
    await db.flush()
    return int(result.rowcount or 0)


async def complete_import_question(
    db: AsyncSession,
    import_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> dict:
    qi = await _get_import_question(db, import_id)
    if qi.status != "pending":
        raise ValueError("仅支持对 pending 记录使用 AI 补全")
    await ensure_ai_parse_allowed(db, operator, request)

    result = await question_pipeline.complete_import(db, operator.id, import_id)
    refreshed = await _get_import_question(db, import_id)
    await write_admin_audit(
        db,
        operator,
        "import.complete",
        "question_import",
        str(import_id),
        severity="important",
        detail={
            "import_id": import_id,
            "batch_id": refreshed.batch_id,
            "missing": result.get("missing", []),
            "from_fallback": result.get("from_fallback", False),
        },
        request=request,
    )
    return {
        "missing": result.get("missing", []),
        "from_fallback": result.get("from_fallback", False),
        "ai_metadata": result.get("ai_metadata", {}),
        "tokens_used": result.get("tokens_used", 0),
        "duration_ms": result.get("duration_ms", 0),
        "item": AdminImportQuestionItem.model_validate(refreshed),
    }


async def create_enrich_task(
    db: AsyncSession,
    batch_id: str,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> AdminImportEnrichResponse:
    summary_result = await db.execute(_batch_summary_query([QuestionImport.batch_id == batch_id]))
    summary_row = summary_result.first()
    if not summary_row:
        raise ValueError("导入批次不存在")
    await ensure_ai_parse_allowed(db, operator, request)

    task_id = f"admin-ai-{uuid4().hex}"
    now = utcnow()
    payload = {
        "task_id": task_id,
        "batch_id": batch_id,
        "status": "pending",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "total_count": int(summary_row.total_count or 0),
        "processed_count": 0,
        "error_message": None,
    }
    await cache.set(_task_key(task_id), payload, ttl=_TASK_TTL_SECONDS)
    await cache.set(_batch_task_key(batch_id), task_id, ttl=_TASK_TTL_SECONDS)
    await write_admin_audit(
        db,
        operator,
        "import.enrich",
        "import_batch",
        batch_id,
        severity="important",
        detail={"task_id": task_id, "batch_id": batch_id, "total_count": payload["total_count"]},
        request=request,
    )
    return AdminImportEnrichResponse(task_id=task_id, batch_id=batch_id, status="pending", created_at=now)


async def get_enrich_status(batch_id: str) -> dict:
    task_id = await cache.get(_batch_task_key(batch_id))
    if not task_id:
        raise ValueError("AI任务不存在")
    payload = await cache.get(_task_key(task_id))
    if not payload:
        raise ValueError("AI任务不存在")
    return payload


async def get_import_question_detail(
    db: AsyncSession,
    import_id: int,
) -> AdminImportQuestionItem:
    """Get full detail for a single import question (includes large fields)."""
    qi = await _get_import_question(db, import_id)
    item = AdminImportQuestionItem.model_validate(qi)
    _apply_risk_to_item(item)
    return item


def _question_conditions(
    status: str | None,
    batch_id: str | None,
    subject: str | None,
    source_type: str | None,
    keyword: str | None,
) -> list:
    conditions = []
    if status:
        conditions.append(QuestionImport.status == status)
    if batch_id:
        conditions.append(QuestionImport.batch_id == batch_id)
    if subject:
        conditions.append(QuestionImport.subject == subject)
    if source_type:
        conditions.append(QuestionImport.source_type == source_type)
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            or_(
                QuestionImport.batch_id.ilike(pattern),
                QuestionImport.source_file.ilike(pattern),
                QuestionImport.parsed_answer.ilike(pattern),
                QuestionImport.parsed_analysis.ilike(pattern),
            )
        )
    return conditions


async def _get_import_question(db: AsyncSession, import_id: int) -> QuestionImport:
    result = await db.execute(select(QuestionImport).where(QuestionImport.id == import_id))
    qi = result.scalar_one_or_none()
    if qi is None:
        raise ValueError("导入题目不存在")
    return qi


async def _get_batch_records(
    db: AsyncSession,
    batch_id: str,
    statuses: set[str] | None = None,
) -> list[QuestionImport]:
    conditions = [QuestionImport.batch_id == batch_id]
    if statuses:
        conditions.append(QuestionImport.status.in_(statuses))
    result = await db.execute(select(QuestionImport).where(*conditions).order_by(QuestionImport.id.asc()))
    records = list(result.scalars().all())
    if not records:
        raise ValueError("导入批次不存在")
    return records
def _batch_conditions(status: str | None, source_type: str | None, keyword: str | None) -> list:
    conditions = []
    if status:
        conditions.append(QuestionImport.status == status)
    if source_type:
        conditions.append(QuestionImport.source_type == source_type)
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(or_(QuestionImport.batch_id.ilike(pattern), QuestionImport.source_file.ilike(pattern)))
    return conditions


def _batch_summary_query(conditions: list):
    return (
        select(
            QuestionImport.batch_id.label("batch_id"),
            func.min(QuestionImport.source_type).label("source_type"),
            func.min(QuestionImport.source_file).label("source_file"),
            func.count().label("total_count"),
            func.sum(case((QuestionImport.status == "pending", 1), else_=0)).label("pending_count"),
            func.sum(case((QuestionImport.status == "approved", 1), else_=0)).label("approved_count"),
            func.sum(case((QuestionImport.status == "rejected", 1), else_=0)).label("rejected_count"),
            func.sum(case((QuestionImport.status == "published", 1), else_=0)).label("published_count"),
            func.sum(case((QuestionImport.ai_generated.is_(True), 1), else_=0)).label("ai_count"),
            func.min(QuestionImport.created_at).label("created_at"),
            func.max(QuestionImport.updated_at).label("updated_at"),
        )
        .where(*conditions)
        .group_by(QuestionImport.batch_id)
    )


def _row_get(data, key: str):
    if isinstance(data, dict):
        return data[key]
    try:
        return data[key]
    except TypeError:
        return getattr(data, key)


def _batch_row_to_dict(row) -> dict:
    data = row._mapping if hasattr(row, "_mapping") else row
    return {
        "batch_id": _row_get(data, "batch_id"),
        "source_type": _row_get(data, "source_type"),
        "source_file": _row_get(data, "source_file"),
        "total_count": int(_row_get(data, "total_count") or 0),
        "pending_count": int(_row_get(data, "pending_count") or 0),
        "approved_count": int(_row_get(data, "approved_count") or 0),
        "rejected_count": int(_row_get(data, "rejected_count") or 0),
        "published_count": int(_row_get(data, "published_count") or 0),
        "ai_count": int(_row_get(data, "ai_count") or 0),
        "created_at": _row_get(data, "created_at"),
        "updated_at": _row_get(data, "updated_at"),
    }


def _task_key(task_id: str) -> str:
    return f"admin:ai:task:{task_id}"


def _batch_task_key(batch_id: str) -> str:
    return f"admin:ai:batch:{batch_id}:task"


async def list_subject_options(db: AsyncSession) -> list[dict]:
    """返回活跃科目列表 [{code, name}]，供下拉框使用。"""
    from app.models.admin import Subject
    result = await db.execute(
        select(Subject.code, Subject.name)
        .where(Subject.is_active.is_(True))
        .order_by(Subject.level.asc(), Subject.sort_order.asc(), Subject.id.asc())
    )
    rows = result.all()
    if rows:
        return [{"code": row.code, "name": row.name} for row in rows]

    # Fallback: extract distinct subjects from existing import data
    from app.models.question_import import QuestionImport
    fb = await db.execute(
        select(QuestionImport.subject)
        .where(QuestionImport.subject.is_not(None), QuestionImport.subject != "")
        .distinct()
        .order_by(QuestionImport.subject.asc())
    )
    return [{"code": row[0], "name": row[0]} for row in fb.all()]
