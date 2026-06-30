"""Stage 7 审核系统 — 审核队列管理与人工修复。

将 Stage 5/6 标准化题目写入 question_imports 暂存区，
提供审核队列查询和人工修复接口。
"""

import logging
import uuid
from datetime import datetime, timezone

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


def _review_now() -> datetime:
    """Return naive UTC datetime for DB storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_blank_option_groups(data: dict | None) -> list[dict]:
    if not isinstance(data, dict):
        return []
    groups = data.get("blank_option_groups")
    if groups is None:
        parsed_content = data.get("parsed_content")
        if isinstance(parsed_content, dict):
            groups = parsed_content.get("blank_option_groups")
    return groups if isinstance(groups, list) else []


def _summarize_blank_option_groups(groups: list[dict]) -> list[dict]:
    summary = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            continue
        options = group.get("options") or {}
        if isinstance(options, dict):
            keys = sorted(str(key).upper() for key in options.keys() if str(key).strip())
        elif isinstance(options, list):
            keys = sorted(
                str(option.get("key") or "").upper()
                for option in options
                if isinstance(option, dict) and str(option.get("key") or "").strip()
            )
        else:
            keys = []
        summary.append({
            "id": group.get("id") or group.get("blank_id") or group.get("label") or index + 1,
            "option_keys": keys,
        })
    return summary


def _log_multi_blank_review_item(
    *,
    batch_id: str,
    qi: QuestionImport,
    source_question: dict,
    stem: str,
) -> None:
    raw_groups = _get_blank_option_groups(source_question)
    parsed_content = qi.parsed_content if isinstance(qi.parsed_content, dict) else {}
    parsed_groups = _get_blank_option_groups(parsed_content)
    if qi.question_type != "multi_blank_choice" and not raw_groups and not parsed_groups:
        return

    logger.warning(
        "multi_blank_choice review item imported",
        extra={
            "import_id": qi.id,
            "batch_id": batch_id,
            "question_type": qi.question_type,
            "stem_preview": stem[:80],
            "parsed_options_is_none": qi.parsed_options is None,
            "blank_option_group_count": len(parsed_groups or raw_groups),
            "blank_option_groups": _summarize_blank_option_groups(parsed_groups or raw_groups),
            "parsed_content_has_blank_option_groups": bool(parsed_groups),
            "raw_data_has_blank_option_groups": bool(raw_groups),
        },
    )


async def _batch_find_duplicate_questions(
    db: AsyncSession,
    subject_hash_pairs: list[tuple[int | str | None, str | None]],
) -> dict[tuple[int | str, str], int]:
    """Batch lookup: (subject_id_or_subject, hash) → question.id for active questions.

    Accepts int (subject_id) or str (legacy subject) as first tuple element.
    """
    valid = [(s, h) for s, h in subject_hash_pairs if s and h]
    if not valid:
        return {}

    unique_pairs: list[tuple[int | str, str]] = list({(s, h) for s, h in valid})
    result_map: dict[tuple[int | str, str], int] = {}

    # Resolve legacy string subjects to IDs (batch)
    str_subjects = list({s for s, _ in unique_pairs if isinstance(s, str)})
    from app.services.admin_subject_service import resolve_subject_id
    subject_code_map: dict[str, int] = {}
    for code in str_subjects:
        resolved = await resolve_subject_id(db, code)
        if resolved is not None:
            subject_code_map[code] = resolved

    for i in range(0, len(unique_pairs), 500):
        chunk = unique_pairs[i:i + 500]
        conditions = []
        for s, h in chunk:
            if isinstance(s, int):
                conditions.append(
                    (Question.subject_id == s) & (Question.question_hash == h)
                )
            else:
                sid = subject_code_map.get(s)
                if sid is not None:
                    conditions.append(
                        (Question.subject_id == sid) & (Question.question_hash == h)
                    )
        from sqlalchemy import or_
        select_cols = [Question.question_hash, Question.id]
        stmt = select(*select_cols).where(
            or_(*conditions),
            Question.is_active == True,  # noqa: E712
        )
        rows = (await db.execute(stmt)).all()
        # Build result using the original pair key format
        matched_hashes: dict[str, int] = {row.question_hash: row.id for row in rows}
        for s, h in chunk:
            if h in matched_hashes:
                result_map[(s, h)] = matched_hashes[h]
    return result_map


async def _batch_find_duplicate_imports(
    db: AsyncSession,
    subject_hash_pairs: list[tuple[int | str | None, str | None]],
) -> dict[tuple[int | str, str], int]:
    """Batch lookup: (subject_id_or_subject, hash) → import.id for non-rejected imports
    whose approved question (if any) is still active.

    Accepts int (subject_id) or str (legacy subject) as first tuple element.
    """
    valid = [(s, h) for s, h in subject_hash_pairs if s and h]
    if not valid:
        return {}

    unique_pairs: list[tuple[int | str, str]] = list({(s, h) for s, h in valid})
    result_map: dict[tuple[int | str, str], int] = {}

    # Resolve legacy string subjects to IDs (batch)
    str_subjects = list({s for s, _ in unique_pairs if isinstance(s, str)})
    from app.services.admin_subject_service import resolve_subject_id
    subject_code_map: dict[str, int] = {}
    for code in str_subjects:
        resolved = await resolve_subject_id(db, code)
        if resolved is not None:
            subject_code_map[code] = resolved

    for i in range(0, len(unique_pairs), 500):
        chunk = unique_pairs[i:i + 500]
        conditions = []
        for s, h in chunk:
            if isinstance(s, int):
                conditions.append(
                    (QuestionImport.subject_id == s) & (QuestionImport.question_hash == h)
                )
            else:
                sid = subject_code_map.get(s)
                if sid is not None:
                    conditions.append(
                        (QuestionImport.subject_id == sid) & (QuestionImport.question_hash == h)
                    )
        from sqlalchemy import or_
        stmt = select(QuestionImport.question_hash, QuestionImport.id, QuestionImport.question_id).where(
            or_(*conditions),
            QuestionImport.status != "rejected",
        )
        rows = (await db.execute(stmt)).all()

        # Batch resolve Question active status (avoid N+1 per-row db.get)
        qids = {row.question_id for row in rows if row.question_id is not None}
        active_qids: set[int] = set()
        if qids:
            q_result = await db.execute(
                select(Question.id).where(
                    Question.id.in_(list(qids)),
                    Question.is_active == True,  # noqa: E712
                )
            )
            active_qids = {qid for qid, in q_result.all()}

        # Build hash→row mapping for quick lookup
        hash_to_rows: dict[str, list] = {}
        for row in rows:
            hash_to_rows.setdefault(row.question_hash, []).append(row)

        for s, h in chunk:
            if (s, h) in result_map:
                continue
            matched_rows = hash_to_rows.get(h, [])
            for row in matched_rows:
                # Skip imports whose approved question was soft-deleted
                if row.question_id is not None and row.question_id not in active_qids:
                    continue
                result_map[(s, h)] = row.id
                break
    return result_map


async def submit_to_review(
    db: AsyncSession,
    questions: list[dict],
    batch_meta: dict | None = None,
    skip_existing: bool = False,
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

    now = _review_now()
    batch_id = f"REVIEW_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    source_type = batch_meta.get("source_type", "pdf")
    source_file = batch_meta.get("source_file", "")
    subject = batch_meta.get("subject", "")
    subject_id = batch_meta.get("subject_id")

    # Resolve legacy subject string to subject_id if needed (once per batch)
    if not subject_id and subject:
        try:
            from app.services.admin_subject_service import resolve_subject_id
            resolved = await resolve_subject_id(db, subject)
            if resolved is not None:
                subject_id = resolved
            else:
                logger.warning("submit_to_review: could not resolve subject=%r to subject_id", subject)
        except Exception:
            logger.warning("submit_to_review: failed to resolve subject=%r", subject, exc_info=True)

    items: list[dict] = []
    written = 0
    skipped = 0
    duplicates_filtered = 0
    # 隐患③ 修复：跟踪本批刚写入的 ORM，commit 后只精确 expunge 这些条目，
    # 不动 session 里其他 attach 的对象。
    pending_qis: list[QuestionImport] = []
    # 暂存每道题的元数据 (q_dict, stem, question_hash)，flush 后用于构建 items。
    # 这样避免在 flush 前读取 qi.id（此时 id 为 None）。
    pending_meta: list[tuple[dict, str, str | None]] = []

    # Pre-compute hashes and batch duplicate lookups (2 queries instead of 2N)
    prepared: list[tuple[dict, str, dict | None, str | None, int | None, str | None]] = []
    subject_hash_pairs: list[tuple[int | str | None, str | None]] = []

    for q in questions:
        if not isinstance(q, dict):
            skipped += 1
            prepared.append((q, "", None, None, None, None))  # type: ignore
            continue

        stem = (q.get("stem") or "").strip()
        if not stem:
            raw_text = (q.get("raw_text") or q.get("raw_question_text") or "").strip()
            if not raw_text:
                skipped += 1
                prepared.append((q, "", None, None, None, None))
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
        qi_subject_id = subject_id or q.get("subject_id") or None
        question_hash = normalizer.build_question_hash(stem, parsed_options, parsed_answer)

        prepared.append((q, stem, parsed_options, qi_subject, qi_subject_id, question_hash))
        # Prefer subject_id (int) for duplicate matching; fall back to subject string
        dup_key = qi_subject_id if qi_subject_id else qi_subject
        subject_hash_pairs.append((dup_key, question_hash))

    # Batch duplicate detection: 2 queries total
    dup_questions = await _batch_find_duplicate_questions(db, subject_hash_pairs)
    dup_imports = await _batch_find_duplicate_imports(db, subject_hash_pairs)

    # Track same-batch duplicates
    # seen_hash_set: 循环中即时检测同批次重复（只需判断 hash 是否存在）
    seen_hash_set: set[str] = set()
    # seen_hashes: flush 后填充 hash→id 映射（用于返回 duplicate_of_import_id）
    seen_hashes: dict[str, int] = {}
    pending_in_batch = 0

    # 隐患② 修复：分批 commit 失去原子性，中途崩溃会留下孤儿 batch_id 记录。
    # 用 try/except 包住整段写入逻辑，失败时按 batch_id 清理已 commit 的部分。
    try:
        for q, stem, parsed_options, qi_subject, qi_subject_id, question_hash in prepared:
            if not stem:
                continue

            # Skip existing questions in the published bank or review pool
            dup_subject = qi_subject_id if qi_subject_id else qi_subject
            dup_key = (dup_subject, question_hash) if (dup_subject and question_hash) else None
            if skip_existing and dup_key and dup_key in dup_questions:
                skipped += 1
                duplicates_filtered += 1
                items.append({
                    "block_index": len(items),
                    "status": "duplicate",
                    "error": "题库中已存在相同题目",
                })
                continue
            if skip_existing and dup_key and dup_key in dup_imports:
                skipped += 1
                duplicates_filtered += 1
                items.append({
                    "block_index": len(items),
                    "status": "duplicate",
                    "error": "审核池中已存在相同题目",
                })
                continue

            # Build duplicate fields from pre-fetched maps
            duplicate_fields = {
                "question_hash": question_hash or None,
                "duplicate_status": "normal",
                "duplicate_of_question_id": None,
                "duplicate_of_import_id": None,
            }
            if dup_key and dup_key in dup_questions:
                duplicate_fields["duplicate_status"] = "possible_duplicate"
                duplicate_fields["duplicate_of_question_id"] = dup_questions[dup_key]
            elif dup_key and dup_key in dup_imports:
                duplicate_fields["duplicate_status"] = "possible_duplicate"
                duplicate_fields["duplicate_of_import_id"] = dup_imports[dup_key]
            elif question_hash and question_hash in seen_hash_set:
                duplicate_fields["duplicate_status"] = "possible_duplicate"
                duplicate_fields["duplicate_of_import_id"] = seen_hashes.get(question_hash)

            # 即时加入 seen_hash_set，后续同批次重复可立即检测到
            if question_hash:
                seen_hash_set.add(question_hash)

            question_type = q.get("question_type", "")
            parsed_answer = (q.get("answer") or "").strip() or None
            parsed_content: dict = {"text": stem}
            if q.get("blank_option_groups"):
                parsed_content["blank_option_groups"] = q.get("blank_option_groups")
            # P1-5: 保留上游 stage 写入的 segments / render_mode
            q_segments = q.get("segments") or (q.get("parsed_content") or {}).get("segments")
            if q_segments:
                parsed_content["render_mode"] = "segments"
                parsed_content["segments"] = q_segments

            # P0: 追加 review 阶段决策到 decision_trace
            q_decision_trace = list(q.get("decision_trace") or [])
            q_decision_trace.append({
                "stage": "review",
                "result": "pending",
                "reason": "written_to_review_queue",
            })
            q["decision_trace"] = q_decision_trace

            qi = QuestionImport(
                batch_id=batch_id,
                source_type=source_type,
                source_file=source_file or None,
                subject_id=qi_subject_id,
                question_type=question_type or None,
                raw_data=q,
                parsed_content=parsed_content,
                parsed_options=parsed_options,
                parsed_answer=parsed_answer,
                parsed_analysis=(q.get("analysis") or "").strip() or None,
                status="pending",
                **duplicate_fields,
                ai_confidence=q.get("confidence_score"),
                created_at=now,
                updated_at=now,
                ai_metadata={
                    "is_valid": q.get("is_valid", True),
                    "errors": q.get("errors", []),
                    "warnings": q.get("warnings", []),
                    "knowledge_points": q.get("knowledge_points", []),
                    "difficulty": q.get("difficulty", 3),
                    "stem_hash": q.get("stem_hash", ""),
                    # P0: 导入管线全链路决策追踪
                    "decision_trace": q.get("decision_trace", []),
                    # Execution Trace: 每 stage 详细执行记录
                    "trace": q.get("trace", []),
                    # P1-2: 透传上游 stage 写入的风险标（值域见
                    # prompts/tasks/ocr_book_pdf_non_question_filter_plan.md §11.3）。
                    # 前端 import-batch 页据此渲染徽章；空列表写 None 减少 JSON 体积。
                    "risk_flags": list(dict.fromkeys(q.get("risk_flags") or [])) or None,
                },
            )
            db.add(qi)
            pending_qis.append(qi)
            # 暂存元数据，flush 后与 pending_qis 一起用于构建 items。
            # 必须在 batch commit 判断之前 append，否则 zip(pending_qis, pending_meta)
            # 长度不一致会丢最后一项。
            pending_meta.append((q, stem, question_hash))
            written += 1
            pending_in_batch += 1

            # P1-B: 每 N 道 flush+commit + 精确 expunge，让 ORM 对象脱离
            # session identity map，GC 才能回收 raw_data / parsed_content 等
            # dict（一道题约 5~30 KB，400 道累积可达 12 MB）。
            # 隐患③：只 expunge 本批刚写入的 qi，不影响调用方在同 session
            # 持有的其他 ORM 实例。
            if pending_in_batch >= _REVIEW_COMMIT_BATCH_SIZE:
                # flush 先分配自增 ID，之后的 ID 依赖操作才安全。
                await db.flush()
                await db.commit()

                # flush 后、expunge 前：填充 seen_hashes 并构建 items。
                # pending_qis 中对象的列属性已在构造时设置，expunge 后仍可访问。
                for _qi, (_q, _stem, _qh) in zip(
                    pending_qis,
                    pending_meta,
                ):
                    if _qh:
                        seen_hashes.setdefault(_qh, _qi.id)
                    _stem_preview = _stem[:50] + "..." if len(_stem) > 50 else _stem
                    items.append({
                        "id": _qi.id,
                        "status": "pending",
                        "confidence_score": _q.get("confidence_score", 0),
                        "stem_preview": _stem_preview,
                        "has_issues": not _q.get("is_valid", True) or bool(_q.get("errors")),
                        "question_hash": _qi.question_hash,
                        "duplicate_status": _qi.duplicate_status,
                        "duplicate_of_question_id": _qi.duplicate_of_question_id,
                        "duplicate_of_import_id": _qi.duplicate_of_import_id,
                    })
                    _log_multi_blank_review_item(
                        batch_id=batch_id, qi=_qi,
                        source_question=_q, stem=_stem,
                    )

                # 回填同批次重复的 duplicate_of_import_id：
                # flush 前 seen_hashes 为空，duplicate_of_import_id 暂为 None；
                # flush 后 seen_hashes 已填充，此时回填第一个同 hash 题目的 ID。
                for _item in items[-len(pending_qis):]:
                    if (
                        _item["duplicate_status"] == "possible_duplicate"
                        and _item["duplicate_of_import_id"] is None
                        and _item["question_hash"]
                        and _item["question_hash"] in seen_hashes
                    ):
                        _item["duplicate_of_import_id"] = seen_hashes[_item["question_hash"]]

                for _qi in pending_qis:
                    db.expunge(_qi)
                pending_qis.clear()
                pending_meta.clear()
                pending_in_batch = 0

        # 收尾：把未达 batch size 的尾部 flush+commit
        if pending_in_batch > 0:
            await db.flush()
            await db.commit()

            # flush 后、expunge 前：填充 seen_hashes 并构建 items
            for _qi, (_q, _stem, _qh) in zip(pending_qis, pending_meta):
                if _qh:
                    seen_hashes.setdefault(_qh, _qi.id)
                _stem_preview = _stem[:50] + "..." if len(_stem) > 50 else _stem
                items.append({
                    "id": _qi.id,
                    "status": "pending",
                    "confidence_score": _q.get("confidence_score", 0),
                    "stem_preview": _stem_preview,
                    "has_issues": not _q.get("is_valid", True) or bool(_q.get("errors")),
                    "question_hash": _qi.question_hash,
                    "duplicate_status": _qi.duplicate_status,
                    "duplicate_of_question_id": _qi.duplicate_of_question_id,
                    "duplicate_of_import_id": _qi.duplicate_of_import_id,
                })
                _log_multi_blank_review_item(
                    batch_id=batch_id, qi=_qi,
                    source_question=_q, stem=_stem,
                )

            # 回填同批次重复的 duplicate_of_import_id（同 batch commit 块逻辑）
            _tail_count = len(pending_qis)
            for _item in items[-_tail_count:]:
                if (
                    _item["duplicate_status"] == "possible_duplicate"
                    and _item["duplicate_of_import_id"] is None
                    and _item["question_hash"]
                    and _item["question_hash"] in seen_hashes
                ):
                    _item["duplicate_of_import_id"] = seen_hashes[_item["question_hash"]]

            for _qi in pending_qis:
                db.expunge(_qi)
            pending_qis.clear()
            pending_meta.clear()
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
        "duplicates_filtered": duplicates_filtered,
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
            "subject_id": qi.subject_id,
            "subject": qi.subject_ref.code if qi.subject_ref else None,
            "subject_name": qi.subject_ref.name if qi.subject_ref else None,
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
        from app.services.pdf_text_normalizer import deduplicate_repeated_text
        parsed_content = dict(qi.parsed_content or {})
        parsed_content["text"] = deduplicate_repeated_text(str(stem).strip())
        qi.parsed_content = parsed_content
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
