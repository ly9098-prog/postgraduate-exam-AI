"""Stage 7 审核系统 — 审核队列管理与人工修复。

将 Stage 5/6 标准化题目写入 question_imports 暂存区，
提供审核队列查询和人工修复接口。
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import asc, delete, func, select, nulls_last
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.question_pipeline import normalizer
from app.models.question import Question
from app.models.question_import import QuestionImport

logger = logging.getLogger(__name__)

# P1-B: review 阶段分批 commit。400+ 道题如果累在单事务里，SQLAlchemy
# session identity map 会一直持有所有 QuestionImport ORM 对象到 commit
# 那一刻；每 N 道 commit + 精确 expunge 把它们放出来，让 GC 能回收。
#
# 隐患③ 修复：使用 db.expunge(qi) 逐个剔除本批写入的 QuestionImport，
# 而不是 db.expunge_all()。后者会把整个 session 里所有 ORM（包括上层
# 调用方在 submit_to_review 之前已 attach 的对象，如 watermark 规则、
# user 等）一并踢掉，副作用过大。
_REVIEW_COMMIT_BATCH_SIZE = 50


def _options_to_dict(options: list[dict]) -> dict | None:
    """[{"key": "A", "text": "..."}] → {"A": "..."}"""
    result = {}
    for opt in options:
        key = opt.get("key", "")
        text = opt.get("text", "")
        if key and text:
            result[str(key).upper()] = str(text)
    return result or None


async def _batch_find_duplicate_questions(
    db: AsyncSession,
    subject_hash_pairs: list[tuple[str | None, str | None]],
) -> dict[str, int]:
    """Batch lookup: hash → question.id for active questions."""
    valid = [(s, h) for s, h in subject_hash_pairs if s and h]
    if not valid:
        return {}
    hashes = list({h for _, h in valid})

    # Split into chunks of 500 for SQLite compatibility
    result_map: dict[str, int] = {}
    for i in range(0, len(hashes), 500):
        chunk = hashes[i:i + 500]
        stmt = select(Question.question_hash, Question.id).where(
            Question.question_hash.in_(chunk),
            Question.is_active == True,  # noqa: E712
        )
        rows = (await db.execute(stmt)).all()
        for row in rows:
            result_map[row.question_hash] = row.id
    return result_map


async def _batch_find_duplicate_imports(
    db: AsyncSession,
    subject_hash_pairs: list[tuple[str | None, str | None]],
) -> dict[str, int]:
    """Batch lookup: hash → import.id for non-rejected imports."""
    valid = [(s, h) for s, h in subject_hash_pairs if s and h]
    if not valid:
        return {}
    hashes = list({h for _, h in valid})

    result_map: dict[str, int] = {}
    for i in range(0, len(hashes), 500):
        chunk = hashes[i:i + 500]
        stmt = select(QuestionImport.question_hash, QuestionImport.id).where(
            QuestionImport.question_hash.in_(chunk),
            QuestionImport.status != "rejected",
        )
        rows = (await db.execute(stmt)).all()
        for row in rows:
            if row.question_hash not in result_map:
                result_map[row.question_hash] = row.id
    return result_map


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
    # 隐患③ 修复：跟踪本批刚写入的 ORM，commit 后只精确 expunge 这些条目，
    # 不动 session 里其他 attach 的对象。
    pending_qis: list[QuestionImport] = []

    # Pre-compute hashes and batch duplicate lookups (2 queries instead of 2N)
    prepared: list[tuple[dict, str, dict | None, str | None, str | None]] = []
    subject_hash_pairs: list[tuple[str | None, str | None]] = []

    for q in questions:
        if not isinstance(q, dict):
            skipped += 1
            prepared.append((q, "", None, None, None))  # type: ignore
            continue

        stem = (q.get("stem") or "").strip()
        if not stem:
            raw_text = (q.get("raw_text") or q.get("raw_question_text") or "").strip()
            if not raw_text:
                skipped += 1
                prepared.append((q, "", None, None, None))
                continue
            stem = raw_text
            q = {
                **q,
                "confidence_score": 0,
                "is_valid": False,
                "errors": [*q.get("errors", []), "empty_stem_raw_text_fallback"],
                "warnings": [*q.get("warnings", []), "题干为空，已用 OCR 原文进入待审核区"],
            }

        options = q.get("options") or []
        question_type = q.get("question_type", "")
        parsed_options = _options_to_dict(options)
        parsed_answer = (q.get("answer") or "").strip() or None
        qi_subject = subject or q.get("subject") or None
        question_hash = normalizer.build_question_hash(stem, parsed_options, parsed_answer)

        prepared.append((q, stem, parsed_options, qi_subject, question_hash))
        subject_hash_pairs.append((qi_subject, question_hash))

    # Batch duplicate detection: 2 queries total
    dup_questions = await _batch_find_duplicate_questions(db, subject_hash_pairs)
    dup_imports = await _batch_find_duplicate_imports(db, subject_hash_pairs)

    # Track same-batch duplicates
    seen_hashes: dict[str, int] = {}
    pending_in_batch = 0

    # 隐患② 修复：分批 commit 失去原子性，中途崩溃会留下孤儿 batch_id 记录。
    # 用 try/except 包住整段写入逻辑，失败时按 batch_id 清理已 commit 的部分。
    try:
        for q, stem, parsed_options, qi_subject, question_hash in prepared:
            if not stem:
                continue

            # Build duplicate fields from pre-fetched maps
            duplicate_fields = {
                "question_hash": question_hash or None,
                "duplicate_status": "normal",
                "duplicate_of_question_id": None,
                "duplicate_of_import_id": None,
            }
            if question_hash and question_hash in dup_questions:
                duplicate_fields["duplicate_status"] = "possible_duplicate"
                duplicate_fields["duplicate_of_question_id"] = dup_questions[question_hash]
            elif question_hash and question_hash in dup_imports:
                duplicate_fields["duplicate_status"] = "possible_duplicate"
                duplicate_fields["duplicate_of_import_id"] = dup_imports[question_hash]
            elif question_hash and question_hash in seen_hashes:
                duplicate_fields["duplicate_status"] = "possible_duplicate"
                duplicate_fields["duplicate_of_import_id"] = seen_hashes[question_hash]

            question_type = q.get("question_type", "")
            parsed_answer = (q.get("answer") or "").strip() or None

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
            pending_qis.append(qi)

            if question_hash:
                seen_hashes.setdefault(question_hash, qi.id)

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
            pending_in_batch += 1

            # P1-B: 每 N 道 commit + 精确 expunge，让 ORM 对象脱离 session
            # identity map，GC 才能回收 raw_data / parsed_content 等 dict
            # （一道题约 5~30 KB，400 道累积可达 12 MB）。
            # 隐患③：只 expunge 本批刚写入的 qi，不影响调用方在同 session
            # 持有的其他 ORM 实例。
            if pending_in_batch >= _REVIEW_COMMIT_BATCH_SIZE:
                await db.commit()
                for _qi in pending_qis:
                    db.expunge(_qi)
                pending_qis.clear()
                pending_in_batch = 0

        # 收尾：把未达 batch size 的尾部 commit；如果上一轮刚 commit 过这里
        # 就是空 commit，对 SQLAlchemy 是 no-op，仅保证函数返回前事务关闭。
        if pending_in_batch > 0:
            await db.commit()
            for _qi in pending_qis:
                db.expunge(_qi)
            pending_qis.clear()
        else:
            await db.commit()
    except Exception as exc:
        # 隐患② 修复：分批 commit 中途失败时，先回滚当前事务，再按 batch_id
        # best-effort 清理之前已 commit 的部分；任何一步失败都只记日志，
        # 不掩盖原始异常。
        logger.exception("submit_to_review failed mid-batch (batch_id=%s): %s", batch_id, exc)
        try:
            await db.rollback()
        except Exception:
            logger.exception("rollback after submit_to_review failure also failed")
        try:
            await db.execute(
                delete(QuestionImport).where(QuestionImport.batch_id == batch_id)
            )
            await db.commit()
            logger.warning(
                "submit_to_review cleaned up orphan batch_id=%s after mid-batch failure",
                batch_id,
            )
        except Exception:
            logger.exception(
                "orphan cleanup for batch_id=%s failed; manual cleanup required", batch_id
            )
        raise

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
