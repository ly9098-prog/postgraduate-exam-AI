"""Stage 7 审核系统 — 审核队列管理与人工修复。

将 Stage 5/6 标准化题目写入 question_imports 暂存区，
提供审核队列查询和人工修复接口。
"""

import uuid
from datetime import datetime

from sqlalchemy import asc, func, select, nulls_last
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.question_pipeline import (
    _build_import_duplicate_fields,
    normalizer,
)
from app.models.question_import import QuestionImport


def _options_to_dict(options: list[dict]) -> dict | None:
    """[{"key": "A", "text": "..."}] → {"A": "..."}"""
    result = {}
    for opt in options:
        key = opt.get("key", "")
        text = opt.get("text", "")
        if key and text:
            result[str(key).upper()] = str(text)
    return result or None


async def submit_to_review(
    db: AsyncSession,
    questions: list[dict],
    batch_meta: dict | None = None,
) -> dict:
    """将 Stage 5/6 标准化题目写入 question_imports 暂存区。

    Args:
        questions: Stage5 输出的题目列表
        batch_meta: {"source_type": "pdf", "source_file": "...", "subject": "..."}

    Returns:
        {"batch_id": str, "total": int, "written": int, "skipped": int, "items": [...]}
    """
    if batch_meta is None:
        batch_meta = {}

    batch_id = f"REVIEW_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    source_type = batch_meta.get("source_type", "pdf")
    source_file = batch_meta.get("source_file", "")
    subject = batch_meta.get("subject", "")

    items: list[dict] = []
    written = 0
    skipped = 0

    for q in questions:
        if not isinstance(q, dict):
            skipped += 1
            continue

        stem = (q.get("stem") or "").strip()
        if not stem:
            skipped += 1
            continue

        options = q.get("options") or []
        question_type = q.get("question_type", "")
        parsed_options = _options_to_dict(options)
        parsed_answer = (q.get("answer") or "").strip() or None
        qi_subject = subject or q.get("subject") or None
        question_hash = normalizer.build_question_hash(stem, parsed_options, parsed_answer)
        duplicate_fields = await _build_import_duplicate_fields(
            db,
            import_id=None,
            subject=qi_subject,
            question_hash=question_hash,
        )

        qi = QuestionImport(
            batch_id=batch_id,
            source_type=source_type,
            source_file=source_file or None,
            subject=qi_subject,
            question_type=question_type or None,
            raw_data=q,
            parsed_content={"text": stem},
            parsed_options=parsed_options,
            parsed_answer=parsed_answer,
            parsed_analysis=(q.get("analysis") or "").strip() or None,
            status="pending",
            **duplicate_fields,
            ai_confidence=q.get("confidence_score"),
            ai_metadata={
                "is_valid": q.get("is_valid", True),
                "errors": q.get("errors", []),
                "warnings": q.get("warnings", []),
                "knowledge_points": q.get("knowledge_points", []),
                "difficulty": q.get("difficulty", 3),
                "stem_hash": q.get("stem_hash", ""),
            },
        )
        db.add(qi)
        await db.flush()

        stem_preview = stem[:50] + "..." if len(stem) > 50 else stem
        items.append({
            "id": qi.id,
            "status": "pending",
            "confidence_score": q.get("confidence_score", 0),
            "stem_preview": stem_preview,
            "has_issues": not q.get("is_valid", True) or bool(q.get("errors")),
            "question_hash": qi.question_hash,
            "duplicate_status": qi.duplicate_status,
            "duplicate_of_question_id": qi.duplicate_of_question_id,
            "duplicate_of_import_id": qi.duplicate_of_import_id,
        })
        written += 1

    await db.commit()

    return {
        "batch_id": batch_id,
        "total": len(questions),
        "written": written,
        "skipped": skipped,
        "items": items,
    }


async def get_review_queue(
    db: AsyncSession,
    status: str | None = None,
    min_confidence: float | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """获取审核队列，低置信度优先。

    Args:
        status: 过滤状态（pending / approved / rejected）
        min_confidence: 最低置信度过滤
        page: 页码（1-based）
        page_size: 每页数量

    Returns:
        {"items": [...], "total": int, "page": int, "page_size": int}
    """
    conditions = []
    if status:
        conditions.append(QuestionImport.status == status)
    if min_confidence is not None:
        conditions.append(QuestionImport.ai_confidence >= min_confidence)

    # count
    count_stmt = select(func.count(QuestionImport.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    # query
    stmt = select(QuestionImport)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(nulls_last(asc(QuestionImport.ai_confidence)), QuestionImport.id)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = (await db.execute(stmt)).scalars().all()

    items = []
    for qi in rows:
        ai_meta = qi.ai_metadata or {}
        items.append({
            "id": qi.id,
            "batch_id": qi.batch_id,
            "source_type": qi.source_type,
            "source_file": qi.source_file,
            "subject": qi.subject,
            "question_type": qi.question_type,
            "parsed_content": qi.parsed_content,
            "parsed_options": qi.parsed_options,
            "parsed_answer": qi.parsed_answer,
            "parsed_analysis": qi.parsed_analysis,
            "question_hash": qi.question_hash,
            "duplicate_status": qi.duplicate_status,
            "duplicate_of_question_id": qi.duplicate_of_question_id,
            "duplicate_of_import_id": qi.duplicate_of_import_id,
            "status": qi.status,
            "ai_confidence": qi.ai_confidence,
            "review_note": qi.review_note,
            "ai_metadata": qi.ai_metadata,
            "errors": ai_meta.get("errors", []) if isinstance(ai_meta, dict) else [],
            "warnings": ai_meta.get("warnings", []) if isinstance(ai_meta, dict) else [],
            "created_at": qi.created_at,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def fix_question(
    db: AsyncSession,
    question_id: int,
    fixes: dict,
) -> dict:
    """人工修复 pending 题目的字段。

    Args:
        question_id: question_imports 记录 ID
        fixes: {"stem": ..., "options": ..., "answer": ..., "analysis": ...}
               所有字段可选

    Returns:
        {"id": int, "status": str, "updated_fields": [...]}

    Raises:
        ValueError: 记录不存在或非 pending 状态
    """
    stmt = select(QuestionImport).where(QuestionImport.id == question_id)
    result = await db.execute(stmt)
    qi = result.scalar_one_or_none()
    if qi is None:
        raise ValueError("导入记录不存在")
    if qi.status != "pending":
        raise ValueError("仅支持修改 pending 状态的记录")

    updated: list[str] = []

    stem = fixes.get("stem")
    if stem is not None:
        qi.parsed_content = {"text": str(stem).strip()}
        updated.append("stem")

    options = fixes.get("options")
    if options is not None:
        qi.parsed_options = _options_to_dict(options)
        updated.append("options")

    answer = fixes.get("answer")
    if answer is not None:
        qi.parsed_answer = str(answer).strip() or None
        updated.append("answer")

    analysis = fixes.get("analysis")
    if analysis is not None:
        qi.parsed_analysis = str(analysis).strip() or None
        updated.append("analysis")

    await db.commit()

    return {
        "id": qi.id,
        "status": qi.status,
        "updated_fields": updated,
    }
