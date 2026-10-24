import logging
import re
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.models.admin import (
    AdminUser,
    QuestionVersion,
    QuestionVersionKnowledgePoint,
    Subject,
)
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.schemas.admin_questions import (
    AdminQuestionAddOptionItem,
    AdminQuestionBatchFailure,
    AdminQuestionBatchResult,
    AdminQuestionPatchRequest,
    AdminQuestionRollbackRequest,
    AdminQuestionToggleActiveRequest,
)
from app.services.admin_audit_service import write_admin_audit
from app.services.knowledge_point_service import load_question_kps
from app.utils.question_content import (
    normalize_segment_type,
    reconcile_student_stem_fields,
)

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
_REVIEW_ALLOWED_TRANSITIONS = {
    "re_pending": ("approved", "rejected"),
    "rejected": ("approved",),
}
_ROLLBACK_QUESTION_FIELDS = (
    "subject_id",
    "question_type",
    "content",
    "options",
    "answer",
    "analysis",
    "difficulty",
    "image_url",
    "source",
    "source_type",
    "source_file",
    "raw_content",
    "year",
)


def _escape_like_keyword(keyword: str) -> str:
    """Escape LIKE wildcards so user input is matched literally, not as pattern.

    Escapes ``\\`` first (it is the escape char once ``ESCAPE '\\'`` is used),
    then ``%`` and ``_``. Without this, a search for ``100%`` would also match
    ``1000``/``100x``, and a LaTeX keyword like ``\\frac`` would be mangled.
    """
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_MAX_FUZZY_SEARCH_TERMS = 8


def _fuzzy_keyword_terms(keyword: str) -> list[str]:
    """Split an admin search into a small set of fuzzy AND terms.

    A user searching ``二叉树 中序`` normally means "contains both concepts", not
    the literal contiguous string including one ASCII space.  Splitting on common
    separators keeps the existing substring semantics for each term while making
    multi-keyword search useful for Chinese question stems.  Terms are de-duplicated
    case-insensitively and capped so an accidental pasted paragraph cannot create an
    unbounded SQL expression.
    """
    raw = keyword.strip()
    if not raw:
        return []
    parts = [part.strip() for part in re.split(r"[\s,，、;；]+", raw) if part.strip()]
    if not parts:
        parts = [raw]

    terms: list[str] = []
    seen: set[str] = set()
    for part in parts:
        marker = part.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        terms.append(part)
        if len(terms) >= _MAX_FUZZY_SEARCH_TERMS:
            break
    return terms


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
        result = await db.execute(
            select(Subject).where(Subject.id == question.subject_id)
        )
        question.subject_ref = result.scalar_one_or_none()


async def _has_question_review_permission(
    db: AsyncSession, operator: AdminPrincipal
) -> bool:
    from app.core.admin_security import _get_permission_names

    return "question:review" in await _get_permission_names(db, operator.role_id)


def _review_audit_detail(
    question: Question,
    before: dict[str, Any],
    after: dict[str, Any],
    reason: str | None,
) -> dict[str, Any]:
    return {
        "question": _question_summary(question),
        "before": before,
        "after": after,
        "reason": reason,
    }


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
    difficulty: int | None = None,
    knowledge_point_id: int | None = None,
    subject_codes: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[Question], int]:
    conditions = []
    if subject_id is not None:
        conditions.append(Question.subject_id == subject_id)
    if subject_codes:
        normalized_codes = tuple(
            dict.fromkeys(
                code.strip() for code in subject_codes if code and code.strip()
            )
        )
        if normalized_codes:
            conditions.append(
                Question.subject_id.in_(
                    select(Subject.id).where(Subject.code.in_(normalized_codes))
                )
            )
    if review_status:
        conditions.append(Question.review_status == review_status)
    if is_active is not None:
        conditions.append(Question.is_active.is_(is_active))
    if question_type:
        conditions.append(Question.question_type == question_type)
    if keyword:
        # Each token is a substring match, while multiple tokens are combined with
        # AND.  Example: ``二叉树 中序`` finds a stem containing both terms even
        # when they are separated by punctuation or other words.
        dialect_name = db.get_bind().dialect.name
        for term_index, term in enumerate(_fuzzy_keyword_terms(keyword)):
            escaped = _escape_like_keyword(term)
            pattern = f"%{escaped}%"

            # aliases 是 JSON 数组：按元素 contains 匹配（跨 dialect）。
            # Give every text() expression a unique bind name; otherwise multiple
            # fuzzy terms would overwrite one another when SQLAlchemy combines them.
            bind_name = f"keyword_pattern_{term_index}"
            if dialect_name == "sqlite":
                alias_match = text(
                    "EXISTS (SELECT 1 FROM json_each(knowledge_points.aliases) "
                    f"WHERE json_each.value LIKE :{bind_name} ESCAPE '\\')"
                ).bindparams(**{bind_name: pattern})
            else:
                alias_match = text(
                    "EXISTS (SELECT 1 FROM json_array_elements_text("
                    "CASE WHEN json_typeof(knowledge_points.aliases) = 'array' "
                    "THEN knowledge_points.aliases ELSE '[]'::json END) "
                    f"AS _alias WHERE _alias ILIKE :{bind_name} ESCAPE '\\')"
                ).bindparams(**{bind_name: pattern})

            kp_qids = (
                select(QuestionKnowledgePoint.question_id)
                .join(
                    KnowledgePoint,
                    KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
                )
                .where(
                    or_(
                        KnowledgePoint.name.ilike(pattern, escape="\\"),
                        alias_match,
                    )
                )
            )
            matching_subject_ids = select(Subject.id).where(
                or_(
                    Subject.name.ilike(pattern, escape="\\"),
                    Subject.code.ilike(pattern, escape="\\"),
                    Subject.path.ilike(pattern, escape="\\"),
                )
            )
            term_conditions = [
                Question.content["stem"].as_string().ilike(pattern, escape="\\"),
                Question.content["text"].as_string().ilike(pattern, escape="\\"),
                Question.content["question"].as_string().ilike(pattern, escape="\\"),
                Question.content["title"].as_string().ilike(pattern, escape="\\"),
                Question.answer.ilike(pattern, escape="\\"),
                Question.analysis.ilike(pattern, escape="\\"),
                Question.raw_content.ilike(pattern, escape="\\"),
                Question.source.ilike(pattern, escape="\\"),
                Question.source_file.ilike(pattern, escape="\\"),
                Question.id.in_(kp_qids),
                Question.subject_id.in_(matching_subject_ids),
            ]
            numeric_term = term.removeprefix("#")
            if numeric_term.isdigit():
                numeric_value = int(numeric_term)
                term_conditions.append(Question.id == numeric_value)
                if len(numeric_term) == 4:
                    term_conditions.append(Question.year == numeric_value)
            conditions.append(or_(*term_conditions))
    if year is not None:
        conditions.append(Question.year == year)
    if import_batch_id:
        escaped_batch_id = _escape_like_keyword(import_batch_id.strip())
        if escaped_batch_id:
            conditions.append(
                Question.import_batch_id.ilike(
                    f"%{escaped_batch_id}%",
                    escape="\\",
                )
            )
    if difficulty is not None:
        conditions.append(Question.difficulty == difficulty)
    if knowledge_point_id is not None:
        conditions.append(
            Question.id.in_(
                select(QuestionKnowledgePoint.question_id).where(
                    QuestionKnowledgePoint.knowledge_point_id == knowledge_point_id
                )
            )
        )

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


async def get_admin_question_detail(
    db: AsyncSession, question_id: int
) -> dict[str, Any]:
    question = await get_admin_question(db, question_id)
    result = await db.execute(
        select(QuestionImport)
        .where(QuestionImport.question_id == question.id)
        .order_by(QuestionImport.id.desc())
    )
    import_record = result.scalars().first()
    if import_record:
        import_record = {
            field: getattr(import_record, field)
            for field in import_record.__mapper__.columns.keys()
        }
        if not import_record.get("duplicate_status"):
            import_record["duplicate_status"] = "normal"
    data = {
        field: getattr(question, field) for field in question.__mapper__.columns.keys()
    }
    kp_map = await load_question_kps(db, [question.id])
    data["knowledge_points"] = kp_map.get(question.id, [])
    data["import_record"] = import_record
    return data


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
    if isinstance(update_data.get("content"), dict):
        # Store one canonical student-visible stem. This prevents future
        # revisions from carrying a newly edited ``text`` plus an old ``stem``.
        update_data["content"] = reconcile_student_stem_fields(update_data["content"])

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

    previous_review_status = question.review_status
    needs_re_review = not await _has_question_review_permission(db, operator)

    # Audit keeps the pre-change values; immutable question revisions are
    # created *after* the mutation reaches its final scalar + KP state.
    before_changed = {
        f: _edit_field_value(question, f, before_kps) for f in changed_fields
    }

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

        await replace_question_knowledge_points(
            db, question, before_kps, source="admin"
        )

    await _resolve_question_subject(db, question)

    if needs_re_review:
        question.review_status = "re_pending"

    after_kp_map = await load_question_kps(db, [question.id])
    after_kps = after_kp_map.get(question.id, [])
    after_changed = {
        f: _edit_field_value(question, f, after_kps) for f in changed_fields
    }

    from app.services.question_revision_service import ensure_question_revision

    await ensure_question_revision(
        db,
        question,
        editor_id=operator.id,
        change_source="admin",
        edit_reason=edit_reason,
    )

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
            "review_status_before": previous_review_status,
            "review_status_after": question.review_status,
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


def ensure_content_segments(
    content: dict[str, Any], stem_text: str | None = None
) -> dict[str, Any]:
    """Upgrade a legacy ``{text, stem}`` content to the segments form when no
    segments exist yet, so an image segment can be appended."""
    segments = content.get("segments")
    if isinstance(segments, list) and segments:
        return content
    out = reconcile_student_stem_fields(content)
    stem = stem_text or out.get("text") or out.get("stem") or ""
    out["render_mode"] = "segments"
    out["segments"] = [{"type": "text", "text": stem}]
    return out


def upsert_stem_image(
    content: dict[str, Any], url: str, replace_url: str | None = None
) -> dict[str, Any]:
    """Add a stem image segment, or replace the segment whose url == replace_url."""
    content = ensure_content_segments(content)
    segments = content["segments"]
    if replace_url:
        normalized_replace_url = replace_url.strip()
        for i, seg in enumerate(segments):
            segment_url = (
                str(seg.get("url") or "").strip() if isinstance(seg, dict) else ""
            )
            if (
                isinstance(seg, dict)
                and normalize_segment_type(seg) == "image"
                and segment_url == normalized_replace_url
            ):
                updated = [*segments]
                updated[i] = {**seg, "url": url}
                out = dict(content)
                out["segments"] = updated
                return out
        raise ValueError("待替换图片不存在")
    out = dict(content)
    out["segments"] = [
        *segments,
        {"type": "image", "url": url, "semantic_role": "content_image"},
    ]
    return out


def remove_stem_image(content: dict[str, Any], url: str) -> dict[str, Any]:
    """Remove the stem image segment whose url matches."""
    segments = content.get("segments")
    if not isinstance(segments, list):
        raise ValueError("待删除图片不存在")
    normalized_url = url.strip()
    kept = [
        s
        for s in segments
        if not (
            isinstance(s, dict)
            and normalize_segment_type(s) == "image"
            and str(s.get("url") or "").strip() == normalized_url
        )
    ]
    if len(kept) == len(segments):
        raise ValueError("待删除图片不存在")
    out = dict(content)
    out["segments"] = kept
    return out


def _resolve_option_storage_key(options: dict[str, Any], key: str) -> str | None:
    """Resolve an option key case-insensitively while preserving stored casing.

    Historical imports may contain ``a``/``b`` keys. Admin endpoints expose
    canonical upper-case targets (``option:A``), so image mutations must not
    fail just because the stored key predates that normalization rule.
    """
    normalized = key.strip().upper()
    for candidate in options:
        if str(candidate).strip().upper() == normalized:
            return candidate
    return None


_OPTION_DIRECT_IMAGE_KEYS = ("url", "image_url", "imageUrl", "src")


def _option_direct_image_key(
    value: dict[str, Any], url: str | None = None
) -> str | None:
    normalized_url = url.strip() if isinstance(url, str) else None
    for key in _OPTION_DIRECT_IMAGE_KEYS:
        candidate = value.get(key)
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        if normalized_url is None or candidate.strip() == normalized_url:
            return key
    return None


def upsert_option_image(
    options: dict[str, Any] | None,
    key: str,
    url: str,
    replace_url: str | None = None,
) -> dict[str, Any]:
    """Add or replace an option image while preserving historical value shapes.

    Newer options store images in ``segments``. Older rows can store a direct
    ``url``/``image_url``/``imageUrl``/``src`` beside text under keys such as
    ``content`` or ``value``. Do not canonicalize those rows just to mutate the
    image, otherwise their text/metadata can be lost.
    """
    requested_key = key.strip().upper()
    result = dict(options or {})
    storage_key = _resolve_option_storage_key(result, requested_key)
    if storage_key is None:
        raise ValueError(f"选项 {requested_key} 不存在")
    cur = result.get(storage_key)

    if isinstance(cur, str):
        current_value: dict[str, Any] = {"text": cur}
    elif isinstance(cur, dict):
        current_value = dict(cur)
    else:
        current_value = {}

    raw_segments = current_value.get("segments")
    segments = (
        [s for s in raw_segments if isinstance(s, dict)]
        if isinstance(raw_segments, list)
        else []
    )

    if replace_url:
        normalized_replace_url = replace_url.strip()
        for i, seg in enumerate(segments):
            if str(seg.get("url") or "").strip() == normalized_replace_url:
                updated = [*segments]
                updated[i] = {**seg, "url": url}
                current_value["segments"] = updated
                result[storage_key] = current_value
                return result

        direct_key = _option_direct_image_key(current_value, normalized_replace_url)
        if direct_key is not None:
            current_value[direct_key] = url
            result[storage_key] = current_value
            return result
        raise ValueError("待替换图片不存在")

    current_value["segments"] = [
        *segments,
        {"type": "image", "url": url, "semantic_role": "option_image"},
    ]
    result[storage_key] = current_value
    return result


def remove_option_image(
    options: dict[str, Any] | None, key: str, url: str
) -> dict[str, Any]:
    """Remove a segment-based or legacy direct option image reference."""
    requested_key = key.strip().upper()
    result = dict(options or {})
    storage_key = _resolve_option_storage_key(result, requested_key)
    if storage_key is None:
        raise ValueError(f"选项 {requested_key} 不存在")
    cur = result[storage_key]
    if not isinstance(cur, dict):
        raise ValueError("待删除图片不存在")

    normalized_url = url.strip()
    current_value = dict(cur)
    removed = False

    raw_segments = current_value.get("segments")
    if isinstance(raw_segments, list):
        kept = [
            segment
            for segment in raw_segments
            if not (
                isinstance(segment, dict)
                and str(segment.get("url") or "").strip() == normalized_url
            )
        ]
        if len(kept) != len(raw_segments):
            removed = True
            if kept:
                current_value["segments"] = kept
            else:
                current_value.pop("segments", None)

    direct_key = _option_direct_image_key(current_value, normalized_url)
    if direct_key is not None:
        removed = True
        current_value.pop(direct_key, None)

    if not removed:
        raise ValueError("待删除图片不存在")

    # A plain-text option promoted to {text, segments} by upload should return
    # to its original compact string shape after the last image is removed.
    if set(current_value) == {"text"} and isinstance(current_value.get("text"), str):
        result[storage_key] = current_value["text"]
    else:
        result[storage_key] = current_value
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
        if not report.safe_to_delete:
            if report.errors:
                logger.warning(
                    "question asset deletion retained because reference scan was incomplete url=%s errors=%s",
                    url,
                    report.errors,
                )
            return
        storage = get_question_assets_storage()
        await storage.delete(url)
    except Exception:
        logger.warning(
            "question asset orphan-cleanup skipped for %s", url, exc_info=True
        )


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
    if before["is_active"]:
        from app.services.question_revision_service import ensure_question_revision

        await ensure_question_revision(
            db,
            question,
            editor_id=operator.id,
            change_source="admin",
            edit_reason="soft delete",
        )

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
            "failed_items": [{"id": f.id, "error": f.error} for f in failed_items],
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

    if data.is_active and question.review_status == "rejected":
        # Rejected questions must be restored through the dedicated re-review
        # approve path so the re-review audit and revision snapshot are written.
        raise ValueError("已拒绝题目不能通过上下架恢复，请使用重审通过")
    if data.is_active and question.review_status not in ("approved",):
        # Only approved questions may be (re)activated. re_pending must go
        # through review; rejected must go through re-review approve.
        raise ValueError("非已审核题目不能激活")
    before = {"is_active": question.is_active}
    changed = question.is_active != data.is_active
    question.is_active = data.is_active
    if changed:
        from app.services.question_revision_service import ensure_question_revision

        await ensure_question_revision(
            db,
            question,
            editor_id=operator.id,
            change_source="admin",
            edit_reason="toggle active",
        )

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


async def review_admin_question(
    db: AsyncSession,
    question_id: int,
    decision: str,
    operator: AdminPrincipal,
    reason: str | None = None,
    request: Request | None = None,
) -> Question:
    """Re-review an already published question.

    ``re_pending`` is the normal queue entry.  A previously rejected question can
    be restored by a reviewer, but approval never bypasses the active flag.
    """
    if decision not in ("approved", "rejected"):
        raise ValueError("无效的审核操作")
    if decision == "rejected" and not (reason or "").strip():
        raise ValueError("拒绝原因不能为空")

    question = await get_admin_question(db, question_id)
    await _resolve_question_subject(db, question)
    allowed = _REVIEW_ALLOWED_TRANSITIONS.get(str(question.review_status or ""), ())
    if decision not in allowed:
        raise ValueError("该题目当前状态不能执行此审核操作")

    before = {"review_status": question.review_status, "is_active": question.is_active}
    question.review_status = decision
    question.is_active = decision == "approved"

    from app.services.question_revision_service import ensure_question_revision

    await ensure_question_revision(
        db,
        question,
        editor_id=operator.id,
        change_source="admin",
        edit_reason=(reason or "").strip() or "re-review approve",
    )
    await write_admin_audit(
        db,
        operator,
        f"question.{decision}",
        "question",
        question.id,
        severity="important",
        detail=_review_audit_detail(
            question,
            before,
            {"review_status": question.review_status, "is_active": question.is_active},
            (reason or "").strip() or None,
        ),
        request=request,
    )
    return question


async def batch_review_admin_questions(
    db: AsyncSession,
    ids: list[int],
    decision: str,
    operator: AdminPrincipal,
    reason: str | None = None,
    request: Request | None = None,
) -> AdminQuestionBatchResult:
    success_ids: list[int] = []
    failed_items: list[AdminQuestionBatchFailure] = []

    for question_id in ids:
        # Per-item isolation: each review runs in its own savepoint so a
        # non-ValueError DB/runtime failure on one item cannot abort the whole
        # batch. ValueError stays the expected per-item contract (bad state,
        # missing reason, invalid transition); everything else is captured and
        # reported in failed_items rather than propagating to the caller.
        try:
            async with db.begin_nested():
                await review_admin_question(
                    db, question_id, decision, operator, reason, request
                )
            success_ids.append(question_id)
        except ValueError as exc:
            failed_items.append(
                AdminQuestionBatchFailure(id=question_id, error=str(exc))
            )
        except Exception as exc:  # noqa: BLE001 — per-item isolation contract
            logger.warning(
                "question batch review item failed id=%s decision=%s",
                question_id,
                decision,
                exc_info=True,
            )
            failed_items.append(
                AdminQuestionBatchFailure(
                    id=question_id, error=f"处理失败：{type(exc).__name__}"
                )
            )

    await write_admin_audit(
        db,
        operator,
        f"question.batch_{decision}",
        "question_batch",
        None,
        severity="critical",
        detail={
            "requested_ids": ids,
            "success_ids": success_ids,
            "failed_items": [
                {"id": item.id, "error": item.error} for item in failed_items
            ],
            "success_count": len(success_ids),
            "failed_count": len(failed_items),
            "decision": decision,
            "reason": reason,
        },
        request=request,
    )
    return AdminQuestionBatchResult(success_ids=success_ids, failed_items=failed_items)


async def rollback_admin_question(
    db: AsyncSession,
    question_id: int,
    data: AdminQuestionRollbackRequest,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> Question:
    """Restore a mutable projection from an immutable revision.

    Rollback is itself a new revision, not a pointer move.  This preserves the
    audit trail of the rejected/current state and keeps practice records bound to
    the immutable version they were issued from.
    """
    question = await get_admin_question(db, question_id)
    await _resolve_question_subject(db, question)
    target = await db.scalar(
        select(QuestionVersion).where(
            QuestionVersion.question_id == question.id,
            QuestionVersion.version == data.version,
        )
    )
    if target is None:
        raise ValueError("版本不存在")
    if target.subject_id is None:
        raise ValueError("目标版本缺少科目，不能回滚")

    kp_result = await db.execute(
        select(KnowledgePoint.name)
        .join(
            QuestionVersionKnowledgePoint,
            QuestionVersionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
        )
        .where(QuestionVersionKnowledgePoint.question_version_id == target.id)
        .order_by(
            QuestionVersionKnowledgePoint.position,
            QuestionVersionKnowledgePoint.id,
        )
    )
    target_kps = list(kp_result.scalars().all())

    before = build_question_audit_snapshot(
        question,
        (await load_question_kps(db, [question.id])).get(question.id, []),
    )
    for field in _ROLLBACK_QUESTION_FIELDS:
        setattr(question, field, getattr(target, field))
    await db.flush()

    from app.services.knowledge_point_service import (
        replace_question_knowledge_points,
    )

    await replace_question_knowledge_points(db, question, target_kps, source="admin")
    question.review_status = "approved"
    question.is_active = True

    from app.services.question_revision_service import ensure_question_revision

    revision = await ensure_question_revision(
        db,
        question,
        editor_id=operator.id,
        change_source="admin",
        edit_reason=data.reason,
    )
    await write_admin_audit(
        db,
        operator,
        "question.rollback",
        "question",
        question.id,
        severity="critical",
        detail={
            "question": _question_summary(question),
            "before": before,
            "after": build_question_audit_snapshot(
                question,
                (await load_question_kps(db, [question.id])).get(question.id, []),
            ),
            "target_version": int(target.version),
            "new_version": int(revision.version),
            "reason": data.reason,
        },
        request=request,
    )
    return question


def _question_version_payload(
    question_version: QuestionVersion,
    editor_display_name: str | None,
    editor_username: str | None,
) -> dict[str, Any]:
    """Serialize a version and include a stable editor display label.

    Prefer the administrator's display name, then username. Keeping the fallback
    nullable lets the frontend render the numeric editor id if an old record no
    longer has resolvable administrator metadata.
    """
    data = {
        column.key: getattr(question_version, column.key)
        for column in question_version.__mapper__.columns
    }
    data["edited_by_name"] = (
        (editor_display_name or "").strip() or (editor_username or "").strip() or None
    )
    data["change_source"] = str(
        getattr(question_version, "change_source", "system") or "system"
    )
    return data


async def list_question_versions(
    db: AsyncSession, question_id: int, page: int, page_size: int
) -> tuple[list[dict[str, Any]], int]:
    await get_admin_question(db, question_id)
    count_query = (
        select(func.count())
        .select_from(QuestionVersion)
        .where(QuestionVersion.question_id == question_id)
    )
    total = await db.scalar(count_query)
    result = await db.execute(
        select(QuestionVersion, AdminUser.display_name, AdminUser.username)
        .outerjoin(AdminUser, AdminUser.id == QuestionVersion.edited_by)
        .where(QuestionVersion.question_id == question_id)
        .order_by(QuestionVersion.version.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    versions = [
        _question_version_payload(question_version, display_name, username)
        for question_version, display_name, username in result.all()
    ]
    return versions, int(total or 0)


async def get_question_version_detail(
    db: AsyncSession, question_id: int, version: int
) -> dict[str, Any]:
    await get_admin_question(db, question_id)
    result = await db.execute(
        select(QuestionVersion, AdminUser.display_name, AdminUser.username)
        .outerjoin(AdminUser, AdminUser.id == QuestionVersion.edited_by)
        .where(
            QuestionVersion.question_id == question_id,
            QuestionVersion.version == version,
        )
    )
    row = result.one_or_none()
    if not row:
        raise ValueError("版本不存在")
    question_version, editor_display_name, editor_username = row

    kp_result = await db.execute(
        select(KnowledgePoint.name)
        .join(
            QuestionVersionKnowledgePoint,
            QuestionVersionKnowledgePoint.knowledge_point_id == KnowledgePoint.id,
        )
        .where(QuestionVersionKnowledgePoint.question_version_id == question_version.id)
        .order_by(
            QuestionVersionKnowledgePoint.position,
            QuestionVersionKnowledgePoint.id,
        )
    )
    data = _question_version_payload(
        question_version, editor_display_name, editor_username
    )
    data["knowledge_points"] = list(kp_result.scalars().all())
    return data
