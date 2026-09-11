import os
import re
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.admin_questions import (
    AdminQuestionAddOptionsRequest,
    AdminQuestionBatchRequest,
    AdminQuestionBatchResult,
    AdminQuestionDeleteImageRequest,
    AdminQuestionDetail,
    AdminQuestionExportRequest,
    AdminQuestionListItem,
    AdminQuestionPatchRequest,
    AdminQuestionToggleActiveRequest,
    AdminQuestionVersionDetail,
    AdminQuestionVersionListItem,
    validate_image_target,
)
from app.schemas.common import paginated_response
from app.schemas.vector import EmbeddingBackfillRequest
from app.services.admin_question_export_service import build_admin_question_export
from app.services.admin_question_service import (
    batch_delete_admin_questions,
    delete_question_asset_if_orphan,
    get_admin_question,
    get_admin_question_detail,
    get_question_version_detail,
    list_admin_questions,
    list_question_versions,
    merge_options,
    remove_option_image,
    remove_stem_image,
    soft_delete_admin_question,
    toggle_active_admin_question,
    update_admin_question,
    upsert_option_image,
    upsert_stem_image,
)
from app.services.knowledge_point_service import load_question_kps
from app.services.storage_backend import compress_image, get_question_assets_storage
from app.services.streaming_upload_handler import stream_to_temp
from app.utils.question_content import (
    extract_image_urls_from_content,
    normalize_segment_type,
)

router = APIRouter(prefix="/api/admin/v1/questions", tags=["admin-questions"])


def _raise_question_error(exc: ValueError) -> None:
    if str(exc) == "题目不存在":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


def _to_admin_item(question, kps=None) -> AdminQuestionListItem:
    """Serialize a Question into AdminQuestionListItem, injecting knowledge_points
    from the relation table (the ORM column no longer exists)."""
    item = AdminQuestionListItem.model_validate(question)
    if kps is not None:
        item = item.model_copy(update={"knowledge_points": kps})
    return item


def _image_url_from_legacy_entry(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in ("url", "src", "image_url", "imageUrl"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _replace_legacy_image_url(values, old_url: str, new_url: str):
    if not isinstance(values, list):
        return None
    normalized_old = old_url.strip()
    replaced = False
    updated = []
    for value in values:
        if _image_url_from_legacy_entry(value) == normalized_old:
            replaced = True
            if isinstance(value, str):
                updated.append(new_url)
            else:
                next_value = dict(value)
                for key in ("url", "src", "image_url", "imageUrl"):
                    candidate = next_value.get(key)
                    if (
                        isinstance(candidate, str)
                        and candidate.strip() == normalized_old
                    ):
                        next_value[key] = new_url
                        break
                updated.append(next_value)
        else:
            updated.append(value)
    return updated if replaced else None


def _remove_legacy_image_url(values, url: str):
    if not isinstance(values, list):
        return None
    normalized_url = url.strip()
    updated = [
        value
        for value in values
        if _image_url_from_legacy_entry(value) != normalized_url
    ]
    return updated if len(updated) != len(values) else None


def _rendered_content_image_urls(content) -> set[str]:
    if not isinstance(content, dict):
        return set()
    segments = content.get("segments")
    if not isinstance(segments, list):
        return set()
    urls: set[str] = set()
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        if normalize_segment_type(segment) not in {
            "image",
            "math_image",
            "table_image",
            "code_image",
        }:
            continue
        url = segment.get("url")
        if isinstance(url, str) and url.strip():
            urls.add(url.strip())
    return urls


def _merge_content_image_urls_with_legacy(question, new_content):
    """Refresh the structured-image mirror without dropping legacy-only images.

    ``image_url`` is a mirror of plain image segments on newer rows, but older
    rows can also contain additional images that do not exist in ``content``.
    Mutating one structured image must not silently discard those legacy-only
    references.
    """
    result = list(extract_image_urls_from_content(new_content) or [])
    seen = {url.strip() for url in result if isinstance(url, str) and url.strip()}
    old_rendered_urls = _rendered_content_image_urls(question.content)
    if isinstance(question.image_url, list):
        for value in question.image_url:
            raw = _image_url_from_legacy_entry(value)
            if not raw or raw in old_rendered_urls or raw in seen:
                continue
            result.append(value)
            seen.add(raw)
    return result or None


_LEGACY_OPTION_CONTENT_FIELDS = ("options", "parsed_options", "option_list")
_OPTION_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _coerce_legacy_option_mapping(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        result = {}
        for index, item in enumerate(value):
            if item is None:
                continue
            fallback_key = (
                _OPTION_LABELS[index] if index < len(_OPTION_LABELS) else str(index + 1)
            )
            key = fallback_key
            if isinstance(item, dict):
                for field in ("key", "label", "name"):
                    candidate = item.get(field)
                    if isinstance(candidate, str) and candidate.strip():
                        key = candidate.strip().upper()
                        break
                result[key] = dict(item)
            else:
                result[key] = str(item)
        return result
    if isinstance(value, str):
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        result = {}
        for line in lines:
            match = re.match(
                r"^([A-Za-z0-9一二三四五六七八九十]+)\s*[.、，,]\s*(.*)$",
                line,
            )
            if match:
                key = match.group(1).upper()
                text = match.group(2).strip()
            else:
                key = str(len(result) + 1)
                text = line
            if key in result:
                continue
            result[key] = text
        return result
    return None


def _effective_question_options(question):
    """Resolve the same legacy option fallback that the admin UI displays.

    Current rows use ``question.options``. Historical imports may keep the only
    editable option mapping under ``content.options`` / ``parsed_options`` /
    ``option_list``; immediate option mutations should work for those rows too.
    """
    if isinstance(question.options, dict) and question.options:
        return question.options
    content = question.content if isinstance(question.content, dict) else {}
    for field in _LEGACY_OPTION_CONTENT_FIELDS:
        value = _coerce_legacy_option_mapping(content.get(field))
        if value:
            return value
    return question.options


def _option_mutation_patch(
    question, options, edit_reason: str | None
) -> AdminQuestionPatchRequest:
    """Keep legacy content-level option mirrors synchronized when present.

    Without this, an image removed from the top-level options can remain hidden
    in ``content.options`` and continue counting as a live asset reference.
    """
    content = question.content if isinstance(question.content, dict) else None
    if not content or not any(
        field in content for field in _LEGACY_OPTION_CONTENT_FIELDS
    ):
        return AdminQuestionPatchRequest(options=options, edit_reason=edit_reason)

    next_content = dict(content)
    for field in _LEGACY_OPTION_CONTENT_FIELDS:
        if field in next_content:
            next_content[field] = options
    return AdminQuestionPatchRequest(
        content=next_content,
        options=options,
        edit_reason=edit_reason,
    )


@router.get("")
async def list_questions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    subject_id: int | None = None,
    review_status: str | None = None,
    is_active: bool | None = Query(None),
    question_type: str | None = None,
    keyword: str | None = None,
    year: int | None = None,
    import_batch_id: str | None = None,
    difficulty: int | None = Query(None, ge=1, le=5),
    knowledge_point_id: int | None = Query(None, ge=1),
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    questions, total = await list_admin_questions(
        db,
        page,
        page_size,
        subject_id,
        review_status,
        is_active,
        question_type,
        keyword,
        year,
        import_batch_id,
        difficulty,
        knowledge_point_id,
    )
    kp_map = await load_question_kps(db, [q.id for q in questions])
    return paginated_response(
        [
            _to_admin_item(question, kp_map.get(question.id, []))
            for question in questions
        ],
        total,
        page,
        page_size,
    )


@router.post("/export")
async def export_questions(
    data: AdminQuestionExportRequest,
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    """Export selected questions, or the current filter result, as CSV/DOCX."""
    try:
        content, filename, media_type = await build_admin_question_export(db, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/batch-delete", response_model=AdminQuestionBatchResult)
async def batch_delete_questions(
    data: AdminQuestionBatchRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:delete")),
    db: AsyncSession = Depends(get_db),
):
    result = await batch_delete_admin_questions(db, data.ids, current_admin, request)
    await db.commit()
    return result


@router.post("/embeddings/backfill")
async def backfill_embeddings(
    data: EmbeddingBackfillRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    """批量回填题目 embedding 向量。

    支持游标分页：传入 after_id 从上次停止的位置继续。
    事务边界：API 层负责批次级提交，单条失败通过 savepoint 隔离。
    """
    from app.schemas.vector import EmbeddingBackfillResponse
    from app.services import vector_retrieval_service
    from app.services.admin_audit_service import write_admin_audit

    try:
        result = await vector_retrieval_service.backfill_question_embeddings(
            db=db,
            subject=data.subject,
            limit=data.limit,
            force=data.force,
            after_id=data.after_id,
        )
        await write_admin_audit(
            db,
            current_admin,
            "question.backfill_embeddings",
            "question",
            None,
            severity="normal",
            detail={
                "subject": data.subject,
                "limit": data.limit,
                "force": data.force,
                "after_id": data.after_id or 0,
                "processed": result.get("total", 0),
                "success_count": (
                    result.get("created", 0)
                    + result.get("updated", 0)
                    + result.get("skipped", 0)
                ),
                "failed_count": result.get("failed", 0),
            },
            request=request,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return EmbeddingBackfillResponse(**result)


@router.get("/embeddings/status")
async def embedding_status(
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    """查看向量功能状态和 embedding 统计。"""
    from app.schemas.vector import EmbeddingStatusResponse
    from app.services import vector_retrieval_service

    result = await vector_retrieval_service.get_embedding_status(db)
    return EmbeddingStatusResponse(**result)


@router.get("/{question_id}", response_model=AdminQuestionDetail)
async def get_question(
    question_id: int,
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_admin_question_detail(db, question_id)
    except ValueError as exc:
        _raise_question_error(exc)


@router.patch("/{question_id}", response_model=AdminQuestionListItem)
async def patch_question(
    question_id: int,
    data: AdminQuestionPatchRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        question = await update_admin_question(
            db, question_id, data, current_admin, request
        )
        await db.commit()
        await db.refresh(question)
        kp_map = await load_question_kps(db, [question.id])
        return _to_admin_item(question, kp_map.get(question.id, []))
    except ValueError as exc:
        await db.rollback()
        _raise_question_error(exc)
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.delete("/{question_id}")
async def delete_question(
    question_id: int,
    request: Request,
    current_admin=Depends(require_permissions("question:delete")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await soft_delete_admin_question(db, question_id, current_admin, request)
        await db.commit()
        return {"status": "ok"}
    except ValueError as exc:
        await db.rollback()
        _raise_question_error(exc)


@router.patch("/{question_id}/toggle-active", response_model=AdminQuestionListItem)
async def toggle_active_question(
    question_id: int,
    data: AdminQuestionToggleActiveRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        question = await toggle_active_admin_question(
            db, question_id, data, current_admin, request
        )
        await db.commit()
        await db.refresh(question)
        kp_map = await load_question_kps(db, [question.id])
        return _to_admin_item(question, kp_map.get(question.id, []))
    except ValueError as exc:
        await db.rollback()
        _raise_question_error(exc)


_QUESTION_IMAGE_MAX_SIZE = 10 * 1024 * 1024


async def _upload_question_asset(file: UploadFile, question_id: int) -> str:
    """Stream, compress and store a question image under static/question-assets."""
    ctype = (file.content_type or "").lower()
    if ctype and not ctype.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持图片文件"
        )
    filename = file.filename or "question-image.png"
    suffix = os.path.splitext(filename)[1] or ".png"
    try:
        tmp = await stream_to_temp(
            file, max_size=_QUESTION_IMAGE_MAX_SIZE, suffix=suffix
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    try:
        if tmp.size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="图片内容为空"
            )
        with open(tmp.path, "rb") as fh:
            data = fh.read(_QUESTION_IMAGE_MAX_SIZE + 1)
        compressed = compress_image(data)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="图片格式无效或尺寸过大",
        ) from exc
    finally:
        tmp.close()
    if compressed.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = ".png"
    elif compressed.startswith(b"RIFF") and compressed[8:12] == b"WEBP":
        ext = ".webp"
    else:
        ext = ".jpg"
    storage = get_question_assets_storage()
    storage_key = f"{question_id}/{uuid.uuid4().hex}{ext}"
    return await storage.upload(storage_key, compressed)


@router.post("/{question_id}/options", response_model=AdminQuestionListItem)
async def add_question_options(
    question_id: int,
    data: AdminQuestionAddOptionsRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        question = await get_admin_question(db, question_id)
        if question.question_type not in ("single_choice", "multiple_choice"):
            raise ValueError("该题型不支持添加选项")
        merged = merge_options(_effective_question_options(question), data.options)
        question = await update_admin_question(
            db,
            question_id,
            _option_mutation_patch(question, merged, data.edit_reason),
            current_admin,
            request,
        )
        await db.commit()
        await db.refresh(question)
        kp_map = await load_question_kps(db, [question.id])
        return _to_admin_item(question, kp_map.get(question.id, []))
    except ValueError as exc:
        await db.rollback()
        _raise_question_error(exc)
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/{question_id}/images", response_model=AdminQuestionListItem)
async def upload_question_image(
    question_id: int,
    request: Request,
    file: UploadFile = File(...),
    target: str = Form(...),
    replace_url: str | None = Form(default=None),
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        target = validate_image_target(target)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    # 先校验题目存在与权限，再上传：非法请求不浪费对象存储往返。
    try:
        question = await get_admin_question(db, question_id)
    except ValueError as exc:
        _raise_question_error(exc)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    url = await _upload_question_asset(file, question_id)
    try:
        if target == "stem":
            try:
                new_content = upsert_stem_image(question.content, url, replace_url)
            except ValueError:
                legacy_image_url = (
                    _replace_legacy_image_url(question.image_url, replace_url, url)
                    if replace_url
                    else None
                )
                if legacy_image_url is None:
                    raise
                patch = AdminQuestionPatchRequest(
                    image_url=legacy_image_url,
                    edit_reason="替换题干图片",
                )
            else:
                new_image_url = _merge_content_image_urls_with_legacy(
                    question, new_content
                )
                patch = AdminQuestionPatchRequest(
                    content=new_content,
                    image_url=new_image_url,
                    edit_reason="插入/替换题干图片",
                )
        else:
            key = target.split(":", 1)[1]
            new_options = upsert_option_image(
                _effective_question_options(question), key, url, replace_url
            )
            patch = _option_mutation_patch(
                question,
                new_options,
                f"插入/替换选项 {key} 图片",
            )
        question = await update_admin_question(
            db, question_id, patch, current_admin, request
        )
        await db.commit()
        await db.refresh(question)
    except ValueError as exc:
        await db.rollback()
        await delete_question_asset_if_orphan(db, url)
        _raise_question_error(exc)
    except PermissionError as exc:
        await db.rollback()
        await delete_question_asset_if_orphan(db, url)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except Exception:
        await db.rollback()
        await delete_question_asset_if_orphan(db, url)
        raise
    if replace_url and replace_url != url:
        await delete_question_asset_if_orphan(db, replace_url)
    kp_map = await load_question_kps(db, [question.id])
    return _to_admin_item(question, kp_map.get(question.id, []))


@router.delete("/{question_id}/images", response_model=AdminQuestionListItem)
async def delete_question_image(
    question_id: int,
    data: AdminQuestionDeleteImageRequest,
    request: Request,
    current_admin=Depends(require_permissions("question:write")),
    db: AsyncSession = Depends(get_db),
):
    try:
        question = await get_admin_question(db, question_id)
        if data.target == "stem":
            try:
                new_content = remove_stem_image(question.content, data.url)
            except ValueError:
                legacy_image_url = _remove_legacy_image_url(
                    question.image_url, data.url
                )
                if legacy_image_url is None:
                    raise
                patch = AdminQuestionPatchRequest(
                    image_url=legacy_image_url or None,
                    edit_reason=data.edit_reason or "删除题干图片",
                )
            else:
                new_image_url = _merge_content_image_urls_with_legacy(
                    question, new_content
                )
                patch = AdminQuestionPatchRequest(
                    content=new_content,
                    image_url=new_image_url,
                    edit_reason=data.edit_reason or "删除题干图片",
                )
        else:
            key = data.target.split(":", 1)[1]
            new_options = remove_option_image(
                _effective_question_options(question), key, data.url
            )
            patch = _option_mutation_patch(
                question,
                new_options,
                data.edit_reason or f"删除选项 {key} 图片",
            )
        question = await update_admin_question(
            db, question_id, patch, current_admin, request
        )
        await db.commit()
        await db.refresh(question)
    except ValueError as exc:
        await db.rollback()
        _raise_question_error(exc)
    except PermissionError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    await delete_question_asset_if_orphan(db, data.url)
    kp_map = await load_question_kps(db, [question.id])
    return _to_admin_item(question, kp_map.get(question.id, []))


@router.get("/{question_id}/versions")
async def list_versions(
    question_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        versions, total = await list_question_versions(db, question_id, page, page_size)
        return paginated_response(
            [AdminQuestionVersionListItem.model_validate(item) for item in versions],
            total,
            page,
            page_size,
        )
    except ValueError as exc:
        _raise_question_error(exc)


@router.get(
    "/{question_id}/versions/{version}", response_model=AdminQuestionVersionDetail
)
async def get_version(
    question_id: int,
    version: int,
    _=Depends(require_permissions("question:read")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_question_version_detail(db, question_id, version)
    except ValueError as exc:
        _raise_question_error(exc)
