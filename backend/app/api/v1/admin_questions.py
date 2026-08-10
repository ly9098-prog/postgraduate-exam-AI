import os
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
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import require_permissions
from app.core.database import get_db
from app.schemas.admin_questions import (
    AdminQuestionAddOptionsRequest,
    AdminQuestionBatchRequest,
    AdminQuestionBatchResult,
    AdminQuestionDeleteImageRequest,
    AdminQuestionDetail,
    AdminQuestionListItem,
    AdminQuestionPatchRequest,
    AdminQuestionToggleActiveRequest,
    AdminQuestionVersionDetail,
    AdminQuestionVersionListItem,
    validate_image_target,
)
from app.schemas.common import paginated_response
from app.schemas.vector import EmbeddingBackfillRequest
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
from app.utils.question_content import extract_image_urls_from_content

router = APIRouter(prefix="/api/admin/v1/questions", tags=["admin-questions"])


def _raise_question_error(exc: ValueError) -> None:
    if str(exc) == "题目不存在":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _to_admin_item(question, kps=None) -> AdminQuestionListItem:
    """Serialize a Question into AdminQuestionListItem, injecting knowledge_points
    from the relation table (the ORM column no longer exists)."""
    item = AdminQuestionListItem.model_validate(question)
    if kps is not None:
        item = item.model_copy(update={"knowledge_points": kps})
    return item


@router.get("")
async def list_questions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    subject_id: int | None = None,
    review_status: str | None = None,
    is_active: bool | None = Query(True),
    question_type: str | None = None,
    keyword: str | None = None,
    year: int | None = None,
    import_batch_id: str | None = None,
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
    )
    kp_map = await load_question_kps(db, [q.id for q in questions])
    return paginated_response(
        [_to_admin_item(question, kp_map.get(question.id, [])) for question in questions],
        total,
        page,
        page_size,
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
        question = await update_admin_question(db, question_id, data, current_admin, request)
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
        question = await toggle_active_admin_question(db, question_id, data, current_admin, request)
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持图片文件")
    filename = file.filename or "question-image.png"
    suffix = os.path.splitext(filename)[1] or ".png"
    try:
        tmp = await stream_to_temp(file, max_size=_QUESTION_IMAGE_MAX_SIZE, suffix=suffix)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    try:
        if tmp.size == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片内容为空")
        with open(tmp.path, "rb") as fh:
            data = fh.read(_QUESTION_IMAGE_MAX_SIZE + 1)
        compressed = compress_image(data)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="图片格式无效或尺寸过大") from exc
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
        merged = merge_options(question.options, data.options)
        question = await update_admin_question(
            db,
            question_id,
            AdminQuestionPatchRequest(options=merged, edit_reason=data.edit_reason),
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
    url = await _upload_question_asset(file, question_id)
    try:
        question = await get_admin_question(db, question_id)
        if target == "stem":
            new_content = upsert_stem_image(question.content, url, replace_url)
            new_image_url = extract_image_urls_from_content(new_content)
            patch = AdminQuestionPatchRequest(
                content=new_content,
                image_url=new_image_url,
                edit_reason="插入/替换题干图片",
            )
        else:
            key = target.split(":", 1)[1]
            new_options = upsert_option_image(question.options, key, url, replace_url)
            patch = AdminQuestionPatchRequest(
                options=new_options,
                edit_reason=f"插入/替换选项 {key} 图片",
            )
        question = await update_admin_question(db, question_id, patch, current_admin, request)
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
            new_content = remove_stem_image(question.content, data.url)
            new_image_url = extract_image_urls_from_content(new_content)
            patch = AdminQuestionPatchRequest(
                content=new_content,
                image_url=new_image_url,
                edit_reason=data.edit_reason or "删除题干图片",
            )
        else:
            key = data.target.split(":", 1)[1]
            new_options = remove_option_image(question.options, key, data.url)
            patch = AdminQuestionPatchRequest(
                options=new_options,
                edit_reason=data.edit_reason or f"删除选项 {key} 图片",
            )
        question = await update_admin_question(db, question_id, patch, current_admin, request)
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
        return paginated_response([AdminQuestionVersionListItem.model_validate(item) for item in versions], total, page, page_size)
    except ValueError as exc:
        _raise_question_error(exc)


@router.get("/{question_id}/versions/{version}", response_model=AdminQuestionVersionDetail)
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
