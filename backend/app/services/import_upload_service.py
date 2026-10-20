"""Shared Public/Admin upload entry; format paths own queue admission."""

import os

from app.schemas.import_review import PipelineUploadResponse
from app.services import import_pipeline_service as runtime
from app.services.import_document_upload import start_document_upload
from app.services.import_excel_upload import start_excel_upload
from app.services.import_image_upload import start_image_upload
from app.services.import_upload_request import UploadRequest
from app.services.upload_validator import UploadValidator, get_upload_validator
from app.utils.sentry_utils import set_tag


def _validate_upload(
    request: UploadRequest,
) -> tuple[int, UploadValidator, bool, bool, bool]:
    if not request.filename:
        raise ValueError("文件名不能为空")
    file_size = os.path.getsize(request.file_path)
    if file_size == 0:
        raise ValueError("文件内容为空")
    set_tag("stage", "upload")
    set_tag("upload.filename", request.filename or "unknown")
    set_tag("upload.type", "pipeline")
    lower_name = request.filename.lower()
    is_pdf = lower_name.endswith(".pdf")
    is_txt = lower_name.endswith(".txt")
    is_excel = lower_name.endswith((".xlsx", ".xls"))
    is_image = lower_name.endswith(runtime._IMAGE_EXTENSIONS)
    if not is_pdf and (not is_txt) and (not is_excel) and (not is_image):
        raise ValueError(
            "仅支持 .xlsx / .xls / .pdf / .txt / .jpg / .jpeg / .png / .webp 文件"
        )
    validator = get_upload_validator()
    validator.validate_file(request.filename, file_size, request.content_type)
    if (request.page_start is not None or request.page_end is not None) and (
        not is_pdf
    ):
        raise ValueError("page_start/page_end 仅适用于 PDF 文件")
    return (file_size, validator, is_pdf, is_excel, is_image)


async def start_import_pipeline(
    *,
    file_path: str,
    filename: str,
    content_type: str | None,
    subject: str | None = None,
    subject_id: int | None = None,
    import_mode: str = "auto",
    enable_ai_repair: bool = True,
    confidence_threshold: float = 0.6,
    image_fast_mode: bool = True,
    page_start: int | None = None,
    page_end: int | None = None,
    created_by: str | None = None,
) -> PipelineUploadResponse:
    request = UploadRequest(
        file_path=file_path,
        filename=filename,
        content_type=content_type,
        subject=subject,
        subject_id=subject_id,
        import_mode=import_mode,
        enable_ai_repair=enable_ai_repair,
        confidence_threshold=confidence_threshold,
        image_fast_mode=image_fast_mode,
        page_start=page_start,
        page_end=page_end,
        created_by=created_by,
    )
    file_size, validator, is_pdf, is_excel, is_image = _validate_upload(request)
    if is_image:
        return await start_image_upload(request, file_size)
    if is_excel:
        return await start_excel_upload(request)
    return await start_document_upload(request, file_size, validator, is_pdf)
