import logging
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.models.admin import QuestionVersion, Subject
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.schemas.admin_questions import (
    AdminQuestionAddOptionItem,
    AdminQuestionBatchFailure,
    AdminQuestionBatchResult,
    AdminQuestionPatchRequest,
    AdminQuestionToggleActiveRequest,
)
from app.services.admin_audit_service import write_admin_audit
from app.services.knowledge_point_service import load_question_kps

logger = logging.getLogger(__name__)


_EDIT_FIELDS = (
    "subject_id",
    "question_type",
    "content",
    "options",
    "answer",
    "analysis",
    "knowledge_points",
    "difficulty",
    "source",
    "source_type",
    "source_file",
    "import_batch_id",
    "raw_content",
    "image_url",
    "year",
)

_CONTENT_PREVIEW_MAX_LENGTH = 200


def _escape_like_keyword(keyword: str) -> str:
    """Escape LIKE wildcards so user input is matched literally, not as pattern.

    Escapes ``\\`` first (it is the escape char once ``ESCAPE '\\'`` is used),
    then ``%`` and ``_``. Without this, a search for ``100%`` would also match
    ``1000``/``100x``, and a LaTeX keyword like ``\\frac`` would be mangled.
    """
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _edit_field_value(question: Question, field: str, kps: list[str]) -> Any:
    """读取编辑字段值；knowledge_points 已从 ORM 列移除，改为显式 kps 列表。"""
    if field == "knowledge_points":
        return kps
    return getattr(question, field)


def build_question_audit_snapshot(question: Question, kps: list[str]) -> dict[str, Any]:
    """Build a complete snapshot of a question for audit logging.

    ``kps`` 是操作发生时的知识点名列表（由调用方从关联表读取），审计必须保存
    操作时值而非未来动态解析。
    """
    # Attempt to resolve subject info
    subject_name = None
    subject_code = None
    if hasattr(question, "subject_ref") and question.subject_ref is not None:
        subject_name = question.subject_ref.name
        subject_code = question.subject_ref.code

    return {
        "id": question.id,
        "subject_id": question.subject_id,
        "subject_code": subject_code,
        "subject_name": subject_name,
        "question_type": question.question_type,
        "content": question.content,
        "options": question.options,
        "answer": question.answer,
        "analysis": question.analysis,
        "knowledge_points": kps,
        "difficulty": question.difficulty,
        "source": question.source,
        "source_type": question.source_type,
        "source_file": question.source_file,
        "import_batch_id": question.import_batch_id,
        "year": question.year,
        "review_status": question.review_status,
        "is_active": question.is_active,
    }


def _content_preview(content: dict | str | None) -> str | None:
    """Extract a short text preview from question content."""
    if content is None:
        return None
    if isinstance(content, str):
        text = content
    elif isinstance(content, dict):
        # Common patterns: {"text": "..."} or {"en": "...", "cn": "..."}
        text = content.get("text")
        if text is None:
            text = content.get("cn")
        if text is None:
            text = content.get("en")
        if text is None:
            text = str(content)
    else:
        text = str(content)
    return text[:_CONTENT_PREVIEW_MAX_LENGTH]


def _question_summary(question: Question) -> dict[str, Any]:
    """Build a light-weight question summary for audit display (no full content)."""
    subject_name = None
    if hasattr(question, "subject_ref") and question.subject_ref is not None:
        subject_name = question.subject_ref.name

    content = getattr(question, "content", None)
    content_preview = _content_preview(content)

    return {
        "id": question.id,
        "content_preview": content_preview,
        "subject_name": subject_name,
        "question_type": question.question_type,
    }


async def _resolve_question_subject(db: AsyncSession, question: Question) -> None:
    """Ensure subject_ref is loaded for a question."""
    if question.subject_ref is None and question.subject_id:
        result = await db.execute(select(Subject).where(Subject.id == question.subject_id))
        question.subject_ref = result.scalar_one_or_none()


async def list_admin_questions(
    db: AsyncSession,
    page: int,
    page_size: int,
    subject_id: int | None = None,
    review_status: str | None = None,
    is_active: bool | None = None,
    question_type: str | None = None,
    keyword: str | None = None,
    year: int | None = None,
    import_batch_id: str | None = None,
) -> tuple[list[Question], int]:
    conditions = []
    if subject_id is not None:
        conditions.append(Question.subject_id == subject_id)
    if review_status:
        conditions.append(Question.review_status == review_status)
    if is_active is not None:
        conditions.append(Question.is_active.is_(is_active))
    if question_type:
        conditions.append(Question.question_type == question_type)
    if keyword:
        escaped = _escape_like_keyword(keyword)
        pattern = f"%{escaped}%"
        # aliases 是 JSON 数组：按元素 contains 匹配（跨 dialect）。
        # SQLite 的 JSON 存储会对中文做 \\uXXXX 转义，CAST(... AS TEXT) 子串匹配会漏；
        # json_each / json_array_elements_text 都会解码后逐元素匹配，两种 dialect 行为一致。
        # 用户输入中的 %/_ 已转义并配合 ESCAPE，避免被当作 LIKE 通配符。
        dialect_name = db.get_bind().dialect.name
        if dialect_name == "sqlite":
            alias_match = text(
                "EXISTS (SELECT 1 FROM json_each(knowledge_points.aliases) "
                "WHERE json_each.value LIKE :pattern ESCAPE '\\')"
            ).bindparams(pattern=pattern)
        else:
            # json_typeof 守卫：aliases 非数组（标量/对象/NULL）时退化为空数组，
            # 避免 json_array_elements_text 对非数组输入抛
            # "cannot extract elements from a scalar / object" 使整个搜索 500。
            alias_match = text(
                "EXISTS (SELECT 1 FROM json_array_elements_text("
                "CASE WHEN json_typeof(knowledge_points.aliases) = 'array' "
                "THEN knowledge_points.aliases ELSE '[]'::json END) "
                "AS _alias WHERE _alias ILIKE :pattern ESCAPE '\\')"
            ).bindparams(pattern=pattern)
        kp_qids = (
            select(QuestionKnowledgePoint.question_id)
            .join(KnowledgePoint, KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id)
            .where(
                or_(
                    KnowledgePoint.name.ilike(pattern, escape="\\"),
                    alias_match,
                )
            )
        )
        conditions.append(
            or_(
                Question.answer.ilike(pattern, escape="\\"),
                Question.analysis.ilike(pattern, escape="\\"),
                Question.raw_content.ilike(pattern, escape="\\"),
                Question.id.in_(kp_qids),
            )
        )
    if year is not None:
        conditions.append(Question.year == year)
    if import_batch_id:
        conditions.append(Question.import_batch_id == import_batch_id)

    query = select(Question)
    count_query = select(func.count()).select_from(Question)
    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = await db.scalar(count_query)
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        query.options(selectinload(Question.subject_ref))
        .order_by(Question.updated_at.desc(), Question.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_admin_question(db: AsyncSession, question_id: int) -> Question:
    question = await db.get(Question, question_id)
    if not question:
        raise ValueError("题目不存在")
    return question


async def get_admin_question_detail(db: AsyncSession, question_id: int) -> dict[str, Any]:
    question = await get_admin_question(db, question_id)
    result = await db.execute(select(QuestionImport).where(QuestionImport.question_id == question.id).order_by(QuestionImport.id.desc()))
    import_record = result.scalars().first()
    if import_record:
        import_record = {
            field: getattr(import_record, field)
            for field in import_record.__mapper__.columns.keys()
        }
        if not import_record.get("duplicate_status"):
            import_record["duplicate_status"] = "normal"
    data = {field: getattr(question, field) for field in question.__mapper__.columns.keys()}
    kp_map = await load_question_kps(db, [question.id])
    data["knowledge_points"] = kp_map.get(question.id, [])
    data["import_record"] = import_record
    return data


async def _next_question_version(db: AsyncSession, question_id: int) -> int:
    version = await db.scalar(select(func.max(QuestionVersion.version)).where(QuestionVersion.question_id == question_id))
    return int(version or 0) + 1


def _question_snapshot(question: Question, kps: list[str]) -> dict[str, Any]:
    """版本历史快照（操作发生前的值）。knowledge_points 用显式 before 列表。"""
    return {
        "content": question.content,
        "options": question.options,
        "answer": question.answer,
        "analysis": question.analysis,
        "difficulty": question.difficulty,
        "knowledge_points": kps,
    }


async def update_admin_question(
    db: AsyncSession,
    question_id: int,
    data: AdminQuestionPatchRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Question:
    question = await get_admin_question(db, question_id)
    await _resolve_question_subject(db, question)

    update_data = data.model_dump(exclude_unset=True)
    edit_reason = update_data.pop("edit_reason", None)

    # 操作发生时的当前知识点（版本快照与审计必须保存操作时值）
    kp_map = await load_question_kps(db, [question.id])
    before_kps = kp_map.get(question.id, [])

    # Compute which fields actually changed (compare old vs new values)
    changed_fields = []
    for f in _EDIT_FIELDS:
        if f in update_data:
            old_val = _edit_field_value(question, f, before_kps)
            new_val = update_data[f]
            if old_val != new_val:
                changed_fields.append(f)

    # No actual changes — skip version creation and audit
    if not changed_fields:
        return question

    # Create version snapshot (only when real changes exist) — 用操作前值
    before_changed = {f: _edit_field_value(question, f, before_kps) for f in changed_fields}
    snapshot = _question_snapshot(question, before_kps)
    db.add(
        QuestionVersion(
            question_id=question.id,
            version=await _next_question_version(db, question.id),
            edited_by=operator.id,
            edit_reason=edit_reason,
            **snapshot,
        )
    )

    # subject_id 优先应用，使后续 KP sync 使用新科目（subject 不变量）
    if "subject_id" in changed_fields:
        question.subject_id = update_data["subject_id"]

    # 应用普通字段（knowledge_points 单独走关联表，不在 setattr）
    for field in changed_fields:
        if field in ("knowledge_points", "subject_id"):
            continue
        setattr(question, field, update_data[field])

    await db.flush()

    # 知识点三况：
    # A 只改 KP → 按当前 subject replace；B 只改 subject → 旧名在新科目重建；C 同改 → 新 subject + 新 KP
    if "knowledge_points" in changed_fields:
        from app.services.knowledge_point_service import (
            replace_question_knowledge_points,
        )

        kp_new = update_data["knowledge_points"]
        if kp_new is None:  # 显式 null = 清空（与旧 column=NULL 行为一致）
            kp_new = []
        await replace_question_knowledge_points(db, question, kp_new, source="admin")
    elif "subject_id" in changed_fields:
        from app.services.knowledge_point_service import (
            replace_question_knowledge_points,
        )

        await replace_question_knowledge_points(db, question, before_kps, source="admin")

    await _resolve_question_subject(db, question)

    after_kp_map = await load_question_kps(db, [question.id])
    after_kps = after_kp_map.get(question.id, [])
    after_changed = {f: _edit_field_value(question, f, after_kps) for f in changed_fields}

    await write_admin_audit(
        db,
        operator,
        "question.update",
        "question",
        question.id,
        severity="important",
        detail={
            "question": _question_summary(question),
            "changed_fields": changed_fields,
            "before": before_changed,
            "after": after_changed,
            "edit_reason": edit_reason,
        },
        request=request,
    )
    return question


# ── question option / image mutation helpers (admin) ────────────────────

_OPTION_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def merge_options(
    existing: dict[str, Any] | None,
    items: list[AdminQuestionAddOptionItem],
) -> dict[str, Any]:
    """Append new options, auto-assigning the next free letter key when an item
    has no explicit key. Rich option values of existing options are preserved."""
    result = dict(existing or {})
    # 大小写不敏感判重：历史小写键 'a' 与自动字母 'A' 视为同一槽位，避免产生重复选项。
    used = {k.upper() for k in result}
    for item in items:
        explicit = item.key
        if explicit:
            key = explicit.upper()
            if key in used:
                raise ValueError(f"选项 {explicit} 已存在")
            result[key] = item.text
            used.add(key)
        else:
            letter = _next_option_letter(used)
            result[letter] = item.text
            used.add(letter)
    return result


def _next_option_letter(used: set[str]) -> str:
    for letter in _OPTION_LETTERS:
        if letter not in used:
            return letter
    raise ValueError("选项数量不能超过 26 个")


def ensure_content_segments(content: dict[str, Any], stem_text: str | None = None) -> dict[str, Any]:
    """Upgrade a legacy ``{text, stem}`` content to the segments form when no
    segments exist yet, so an image segment can be appended."""
    segments = content.get("segments")
    if isinstance(segments, list) and segments:
        return content
    stem = stem_text or content.get("stem") or content.get("text") or ""
    out = dict(content)
    out["render_mode"] = "segments"
    out["segments"] = [{"type": "text", "text": stem}]
    return out


def upsert_stem_image(content: dict[str, Any], url: str, replace_url: str | None = None) -> dict[str, Any]:
    """Add a stem image segment, or replace the segment whose url == replace_url."""
    content = ensure_content_segments(content)
    segments = content["segments"]
    if replace_url:
        for i, seg in enumerate(segments):
            if isinstance(seg, dict) and seg.get("type") == "image" and seg.get("url") == replace_url:
                updated = [*segments]
                updated[i] = {**seg, "url": url}
                out = dict(content)
                out["segments"] = updated
                return out
        raise ValueError("待替换图片不存在")
    out = dict(content)
    out["segments"] = [*segments, {"type": "image", "url": url, "semantic_role": "content_image"}]
    return out


def remove_stem_image(content: dict[str, Any], url: str) -> dict[str, Any]:
    """Remove the stem image segment whose url matches."""
    segments = content.get("segments")
    if not isinstance(segments, list):
        raise ValueError("待删除图片不存在")
    kept = [s for s in segments if not (isinstance(s, dict) and s.get("type") == "image" and s.get("url") == url)]
    if len(kept) == len(segments):
        raise ValueError("待删除图片不存在")
    out = dict(content)
    out["segments"] = kept
    return out


def upsert_option_image(
    options: dict[str, Any] | None,
    key: str,
    url: str,
    replace_url: str | None = None,
) -> dict[str, Any]:
    """Set an option image: append an image segment to ``options[key]``, or
    replace the segment whose url == replace_url. Preserves the option text."""
    key = key.upper()
    result = dict(options or {})
    if key not in result:
        raise ValueError(f"选项 {key} 不存在")
    cur = result.get(key)
    extra: dict[str, Any] = {}
    if isinstance(cur, str):
        text, segments = cur, []
    elif isinstance(cur, dict):
        text = str(cur.get("text") or "")
        segments = [s for s in (cur.get("segments") or []) if isinstance(s, dict)]
        # 保留其他富键（如 semantic_role、is_question_image），避免重写时丢失。
        extra = {k: v for k, v in cur.items() if k not in ("text", "segments")}
    else:
        text, segments = "", []
    if replace_url:
        for i, seg in enumerate(segments):
            if isinstance(seg, dict) and seg.get("url") == replace_url:
                updated = [*segments]
                updated[i] = {**seg, "url": url}
                result[key] = {"text": text, "segments": updated, **extra}
                return result
        raise ValueError("待替换图片不存在")
    result[key] = {
        "text": text,
        "segments": [*segments, {"type": "image", "url": url, "semantic_role": "option_image"}],
        **extra,
    }
    return result


def remove_option_image(options: dict[str, Any] | None, key: str, url: str) -> dict[str, Any]:
    """Remove the image segment matching url from ``options[key]``; degrade the
    rich value back to flat text when no image segments remain."""
    key = key.upper()
    result = dict(options or {})
    if key not in result:
        raise ValueError(f"选项 {key} 不存在")
    cur = result[key]
    if not isinstance(cur, dict) or not isinstance(cur.get("segments"), list):
        raise ValueError("待删除图片不存在")
    kept = [s for s in cur["segments"] if not (isinstance(s, dict) and s.get("url") == url)]
    if len(kept) == len(cur["segments"]):
        raise ValueError("待删除图片不存在")
    text = str(cur.get("text") or "")
    extra = {k: v for k, v in cur.items() if k not in ("text", "segments")}
    if kept:
        result[key] = {"text": text, "segments": kept, **extra}
    elif extra:
        # 仍有富键（如 semantic_role）时保持 dict 形态，避免丢元数据
        result[key] = {"text": text, "segments": [], **extra}
    else:
        result[key] = text
    return result


async def delete_question_asset_if_orphan(db: AsyncSession, url: str) -> None:
    """Best-effort delete of a question asset file once nothing references it."""
    from app.services.asset_reference_service import (
        AssetReferenceService,
        url_to_storage_key,
    )
    from app.services.storage_backend import get_question_assets_storage

    try:
        key = url_to_storage_key(url)
        report = await AssetReferenceService(db).resolve(key)
        if report.reference_count > 0:
            return
        storage = get_question_assets_storage()
        await storage.delete(url)
    except Exception:
        logger.warning("question asset orphan-cleanup skipped for %s", url, exc_info=True)


async def soft_delete_admin_question(
    db: AsyncSession,
    question_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Question:
    question = await get_admin_question(db, question_id)
    await _resolve_question_subject(db, question)

    # Take full snapshot before deletion
    kp_map = await load_question_kps(db, [question.id])
    full_snapshot = build_question_audit_snapshot(question, kp_map.get(question.id, []))

    before = {"is_active": question.is_active}
    question.is_active = False

    await write_admin_audit(
        db,
        operator,
        "question.delete",
        "question",
        question.id,
        severity="critical",
        detail={
            "question": full_snapshot,
            "before": before,
            "after": {"is_active": question.is_active},
            "delete_mode": "soft",
            "question_summary": _question_summary(question),
        },
        request=request,
    )
    return question


async def batch_delete_admin_questions(
    db: AsyncSession,
    ids: list[int],
    operator: AdminPrincipal,
    request: Request | None = None,
) -> AdminQuestionBatchResult:
    success_ids: list[int] = []
    failed_items: list[AdminQuestionBatchFailure] = []
    questions_summary: list[dict] = []

    for qid in ids:
        try:
            question = await soft_delete_admin_question(db, qid, operator, request)
            success_ids.append(qid)
            questions_summary.append(_question_summary(question))
        except ValueError as exc:
            failed_items.append(AdminQuestionBatchFailure(id=qid, error=str(exc)))

    # Also write a batch summary log
    await write_admin_audit(
        db,
        operator,
        "question.batch_delete",
        "question_batch",
        None,
        severity="critical",
        detail={
            "requested_ids": ids,
            "success_ids": success_ids,
            "failed_items": [
                {"id": f.id, "error": f.error} for f in failed_items
            ],
            "success_count": len(success_ids),
            "failed_count": len(failed_items),
            "questions": questions_summary,
        },
        request=request,
    )

    return AdminQuestionBatchResult(success_ids=success_ids, failed_items=failed_items)


async def toggle_active_admin_question(
    db: AsyncSession,
    question_id: int,
    data: AdminQuestionToggleActiveRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Question:
    question = await get_admin_question(db, question_id)
    await _resolve_question_subject(db, question)

    if data.is_active and question.review_status != "approved":
        raise ValueError("非已审核题目不能激活")
    before = {"is_active": question.is_active}
    question.is_active = data.is_active

    await write_admin_audit(
        db,
        operator,
        "question.toggle_active",
        "question",
        question.id,
        severity="important",
        detail={
            "question": _question_summary(question),
            "before": before,
            "after": {"is_active": question.is_active},
        },
        request=request,
    )
    return question


async def list_question_versions(db: AsyncSession, question_id: int, page: int, page_size: int) -> tuple[list[QuestionVersion], int]:
    await get_admin_question(db, question_id)
    count_query = select(func.count()).select_from(QuestionVersion).where(QuestionVersion.question_id == question_id)
    total = await db.scalar(count_query)
    result = await db.execute(
        select(QuestionVersion)
        .where(QuestionVersion.question_id == question_id)
        .order_by(QuestionVersion.version.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), int(total or 0)


async def get_question_version_detail(db: AsyncSession, question_id: int, version: int) -> QuestionVersion:
    await get_admin_question(db, question_id)
    result = await db.execute(select(QuestionVersion).where(QuestionVersion.question_id == question_id, QuestionVersion.version == version))
    question_version = result.scalar_one_or_none()
    if not question_version:
        raise ValueError("版本不存在")
    return question_version
