"""Import pipeline execution, status and shared resource/image helpers.

Upload admission is owned by import_upload_service. Background execution keeps
the existing database, cleanup, status and resource reservation behavior here.
"""

import hashlib
import io
import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.core.database import async_session
from app.core.log_context import bind_log_context, log_event
from app.core.resource_guard import resource_guard
from app.core.time_utils import serialize_utc_datetime, utcnow
from app.features.ocr_layout_blocks import build_pre_extracted_ocr_blocks
from app.features.pipeline_coordinator_entry import run_pipeline
from app.features.pipeline_orchestrator import (
    _set_pipeline_store,
    resume_pipeline_background,
    run_pipeline_background,
)
from app.services.import_image_completion import (
    ImageCompletionRequest,
    finalize_image_pipeline_result,
)
from app.services.import_image_stages import (
    ImageFailurePersistence,
    ImageCompletionPersistence,
    ImageOcrStage,
    ImagePipelineStage,
    ImageStageCheckpointRequest,
    ensure_image_checkpoint,
    run_image_pipeline_stage,
    persist_image_completion,
    persist_image_failure,
    run_prepared_image_ocr,
)
from app.services.import_background_execution import (
    ImportBackgroundExecutionRequest,
    execute_import_background,
)
from app.services.import_background_failure import record_background_pipeline_failure
from app.features.pipeline_orchestrator import (
    get_pipeline_status as _orchestrator_get_pipeline_status,
)
from app.schemas.import_review import PipelineStatusResponse
from app.utils.sentry_utils import capture_exception, set_tag

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def _queue_rejection_message(reason: str) -> str:
    """Turn queue reason codes into an operator-friendly import error."""
    if reason == "redis_unavailable":
        return "任务队列不可用：Redis 未连接或不可达"
    if reason == "queue_full":
        return "任务队列已满，请稍后重试"
    if reason == "staging_unavailable":
        return "暂存文件协调服务不可用，请稍后重试"
    if reason == "staging_object_missing":
        return "暂存文件已不存在或元数据损坏，请重新上传"
    return f"任务提交失败: {reason or 'unknown'}"


# ── Reservation management (Batch 3: ZSET-based admission ordering) ──

_pipeline_reservations: dict[str, tuple[str, str, str, int]] = {}
"""In-memory registry mapping pipeline_id → (token, resource_type, owner_token, generation).

Allows the background task to release the reservation that was acquired
during admission. Both run in the same OS process (v1 or v2 worker).
"""


async def _acquire_pipeline_reservation(pipeline_id: str, resource_type: str) -> str:
    """Acquire a ZSET reservation and store info for background-task release.

    Raises ResourceGuardError if at capacity.
    """
    from app.core.resource_guard import RESOURCE_PRESSURE, ResourceGuardError

    # System-level resource check first
    ok, reason = resource_guard.can_accept_work()
    if not ok:
        raise ResourceGuardError(RESOURCE_PRESSURE, reason)

    token = await resource_guard.acquire_reservation(
        resource_type=resource_type,
        task_id=pipeline_id,
    )
    if not token:
        raise ResourceGuardError(RESOURCE_PRESSURE, f"{resource_type} 并发数已达上限")
    _pipeline_reservations[pipeline_id] = (
        token,
        resource_type,
        resource_guard.process_owner_token,
        0,
    )
    return token


async def _release_pipeline_reservation(pipeline_id: str) -> None:
    """Release the ZSET reservation for a pipeline (called from background task finally)."""
    info = _pipeline_reservations.pop(pipeline_id, None)
    if info is None:
        return
    token, resource_type, owner_token, generation = info
    await resource_guard.release_reservation(
        token=token,
        resource_type=resource_type,
        owner_token=owner_token,
        generation=generation,
    )


def _sha256_of_file(path: str) -> str:
    """Compute SHA-256 of a file without loading it entirely into memory."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_IMAGE_PIPELINE_STORE_SIZE = 200
_IMAGE_PIPELINE_STATUS_TTL_SECONDS = 86400
_IMAGE_PIPELINE_REDIS_PREFIX = "import:image:pipeline"
_image_pipeline_store: dict[str, dict] = {}


def _image_pipeline_key(pipeline_id: str) -> str:
    return f"{_IMAGE_PIPELINE_REDIS_PREFIX}:{pipeline_id}"


def _prune_image_pipeline_store() -> None:
    if len(_image_pipeline_store) <= _MAX_IMAGE_PIPELINE_STORE_SIZE:
        return
    over_limit = len(_image_pipeline_store) - _MAX_IMAGE_PIPELINE_STORE_SIZE
    oldest_ids = sorted(
        _image_pipeline_store,
        key=lambda pid: _image_pipeline_store[pid].get("started_at", ""),
    )[:over_limit]
    for pipeline_id in oldest_ids:
        _image_pipeline_store.pop(pipeline_id, None)


async def _set_image_pipeline_status(image_pipeline_id: str, **updates) -> dict:
    updates.pop("pipeline_id", None)
    status = _image_pipeline_store.setdefault(
        image_pipeline_id,
        {
            "pipeline_id": image_pipeline_id,
            "status": "queued",
            "source_type": "image",
            "stages": {},
            "stats": {},
            "errors": [],
            "batch_id": "",
            "started_at": serialize_utc_datetime(utcnow()),
        },
    )
    if "started_at" in updates and status.get("started_at"):
        updates = {k: v for k, v in updates.items() if k != "started_at"}
    status.update(updates)
    _prune_image_pipeline_store()
    try:
        await cache.set(
            _image_pipeline_key(image_pipeline_id),
            status,
            ttl=_IMAGE_PIPELINE_STATUS_TTL_SECONDS,
        )
    except Exception:
        logger.warning(
            "image pipeline status cache write failed: pipeline_id=%s",
            image_pipeline_id,
        )
    return status


async def _get_image_pipeline_status(pipeline_id: str) -> dict | None:
    try:
        cached = await cache.get(_image_pipeline_key(pipeline_id))
    except Exception:
        logger.warning(
            "image pipeline status cache read failed: pipeline_id=%s", pipeline_id
        )
        cached = None
    if cached is not None:
        _image_pipeline_store[pipeline_id] = cached
        _prune_image_pipeline_store()
        return cached
    return _image_pipeline_store.get(pipeline_id)


def _validate_image_path(path: str) -> tuple[int, int, str]:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise ValueError("图片解析依赖不可用") from exc

    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height = img.size
            image_format = (img.format or "").lower()
    except (UnidentifiedImageError, FileNotFoundError) as exc:
        raise ValueError("图片内容无法解析") from exc
    except Exception as exc:
        raise ValueError("图片内容校验失败") from exc

    if width <= 0 or height <= 0:
        raise ValueError("图片尺寸无效")
    return width, height, image_format


def _build_ocr_text_diagnostics(raw_ocr_text: str, cleaned_text: str) -> dict:
    raw_lines = [line for line in raw_ocr_text.splitlines() if line.strip()]
    cleaned_lines = [line for line in cleaned_text.splitlines() if line.strip()]
    return {
        "raw_text_length": len(raw_ocr_text),
        "cleaned_text_length": len(cleaned_text),
        "raw_line_count": len(raw_lines),
        "cleaned_line_count": len(cleaned_lines),
        "raw_text_preview": raw_ocr_text[:1000],
        "cleaned_text_preview": cleaned_text[:1000],
        "text_length_delta": len(raw_ocr_text) - len(cleaned_text),
        "line_count_delta": len(raw_lines) - len(cleaned_lines),
    }


def _build_ocr_runtime_diagnostics() -> dict:
    from app.core.ocr_isolation import local_paddleocr_available
    from app.core.ocr_runtime_config import get_runtime_config, sanitize_url

    cfg = get_runtime_config()

    return {
        "ocr_enabled": settings.OCR_ENABLED,
        "execution_backend": cfg.execution_backend,
        "remote_url": sanitize_url(cfg.remote_url) if cfg.remote_url else "",
        "use_gpu": cfg.use_gpu,
        "paddleocr_available": local_paddleocr_available(),
    }


async def _run_ocr_via_configured_backend(image_bytes: bytes) -> dict:
    """Run image OCR through the configured OCR worker backend.

    The image-import path used to call ``ocr_executor`` directly, which is a
    deprecated local-process compatibility service.  That silently bypassed
    ``OCR_EXECUTION_BACKEND=paddlex_http`` and therefore used local PaddleOCR
    even when the remote httpx/GPU service was configured.

    This helper uses the application OCR Gateway when available.  For tooling
    or tests where the lifespan Gateway has not been created yet, it creates a
    short-lived worker client from the same runtime config.  Importantly, a
    configured ``paddlex_http`` backend never falls back to local CPU OCR.

    Returns the standard ``WorkerResult.result`` mapping so callers can retain
    OCR boxes/geometry instead of reducing the first OCR pass to plain text.
    """
    from app.core.ocr_runtime_config import get_runtime_config, sanitize_url
    from app.services.ocr_service import get_gateway
    from app.services.ocr_worker_client import create_ocr_worker_client

    cfg = get_runtime_config()
    if not cfg.enabled:
        raise RuntimeError("OCR 功能未启用（OCR_ENABLED=false）")
    if cfg.execution_backend == "disabled":
        raise RuntimeError("OCR 执行后端已禁用（OCR_EXECUTION_BACKEND=disabled）")

    logger.info(
        "image OCR backend selected: backend=%s remote_url=%s use_gpu=%s",
        cfg.execution_backend,
        sanitize_url(cfg.remote_url) if cfg.remote_url else "-",
        cfg.use_gpu,
    )

    gateway = get_gateway()
    worker_client = None
    owns_worker_client = False
    try:
        if gateway is not None and gateway.is_gateway:
            results = await gateway.recognize_pages([(1, image_bytes)])
        else:
            worker_client = create_ocr_worker_client(cfg)
            if worker_client is None:
                raise RuntimeError(
                    f"OCR worker unavailable: execution_backend={cfg.execution_backend}"
                )
            owns_worker_client = True
            results = await worker_client.recognize_batch([(1, image_bytes)])

        if not results:
            raise RuntimeError("OCR 后端未返回识别结果")

        worker_result = results[0]
        result = worker_result.result if isinstance(worker_result.result, dict) else {}
        if worker_result.status != "success" or result.get("failed"):
            stable_code = worker_result.stable_error_code or "ocr.backend_failed"
            detail = result.get("error") or worker_result.error_type or "unknown"
            raise RuntimeError(f"OCR 后端调用失败: {stable_code}: {detail}")

        text = str(result.get("text") or "")
        if not text.strip():
            raise RuntimeError("OCR 后端返回成功，但未识别到文本")
        return result
    except Exception as e:
        logger.error("OCR failed: %s", e)
        raise
    finally:
        if owns_worker_client and worker_client is not None:
            try:
                await worker_client.shutdown()
            except Exception as exc:
                logger.warning("Temporary OCR worker client shutdown failed: %s", exc)


def _build_pre_extracted_ocr_blocks(
    *,
    image_bytes: bytes,
    cleaned_text: str,
    ocr_result: dict,
) -> list[dict]:
    """Backward-compatible historical import for callers and tests."""
    return build_pre_extracted_ocr_blocks(
        image_bytes=image_bytes,
        cleaned_text=cleaned_text,
        ocr_result=ocr_result,
    )


def _build_pre_extracted_ocr_block(
    *,
    image_bytes: bytes,
    cleaned_text: str,
    ocr_result: dict,
) -> dict:
    """Backward-compatible single-block helper for older callers/tests."""
    return _build_pre_extracted_ocr_blocks(
        image_bytes=image_bytes,
        cleaned_text=cleaned_text,
        ocr_result=ocr_result,
    )[0]


def _classify_image_pipeline_result(result: dict, cleaned_text: str) -> str | None:
    if not cleaned_text.strip():
        return "ocr_empty_text"
    split = result.get("diagnostics", {}).get("split", {})
    if split.get("failure_reason") == "text_present_but_no_question_boundary":
        return "text_present_but_split_failed"
    schema_errors = result.get("diagnostics", {}).get("schema_errors", [])
    if any(
        "missing_options" in item.get("errors", [])
        for item in schema_errors
        if isinstance(item, dict)
    ):
        return "missing_options"
    if result.get("status") != "completed":
        return "pipeline_failed"
    return None


async def _fail_image_pipeline(pipeline_id: str, error: str) -> None:
    current = await _get_image_pipeline_status(pipeline_id) or {}
    errors = list(current.get("errors", []))
    errors.append(error)
    stages = dict(current.get("stages", {}))
    if stages:
        active_stage = next(
            (
                name
                for name, stage in reversed(list(stages.items()))
                if stage.get("status") in {"running", "pending"}
            ),
            None,
        )
        if active_stage:
            stages[active_stage] = {
                **stages[active_stage],
                "status": "failed",
                "error": error,
            }
    await _set_image_pipeline_status(
        pipeline_id,
        status="failed",
        errors=errors,
        stages=stages,
        finished_at=serialize_utc_datetime(utcnow()),
    )


async def _run_image_pipeline_with_db(
    pipeline_id: str,
    image_path: str,
    source_file: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
    created_by: str | None = None,
) -> None:
    """图片后台任务：OCR → TXT bytes → 现有导入流水线。"""
    bind_log_context(
        trace_id=options.get("_trace_id"),
        request_id=options.get("_request_id"),
        pipeline_id=pipeline_id,
        source_type="image",
        source_file=source_file,
    )

    log_event(
        logger,
        "import.background.start",
        pipeline_id=pipeline_id,
        source_type="image",
        source_file=source_file,
    )

    set_tag("stage", "upload")
    set_tag("upload.filename", source_file)
    set_tag("upload.type", "image")
    try:
        from app.features import pipeline_checkpoint as ckpt

        await ensure_image_checkpoint(
            ImageStageCheckpointRequest(
                pipeline_id=pipeline_id,
                source_file=source_file,
                created_by=created_by,
                async_session=async_session,
                ensure_record=ckpt.ensure_pipeline_record,
            )
        )
        from app.services.ocr_service import clean_ocr_text

        ocr_stage = await run_prepared_image_ocr(
            ImageOcrStage(
                pipeline_id=pipeline_id,
                image_path=image_path,
                source_file=source_file,
                read_bytes=lambda _path: b"",
                set_stage_tags=lambda stage_name, engine: (
                    set_tag("stage", stage_name),
                    set_tag("ocr.engine", engine),
                ),
                build_runtime_diagnostics=_build_ocr_runtime_diagnostics,
                run_ocr=_run_ocr_via_configured_backend,
                clean_text=clean_ocr_text,
                build_diagnostics=_build_ocr_text_diagnostics,
                build_blocks=_build_pre_extracted_ocr_blocks,
                set_status=_set_image_pipeline_status,
            )
        )
        image_content = ocr_stage.image_bytes
        raw_ocr_text = ocr_stage.stage_result.raw_ocr_text
        raw_text = ocr_stage.stage_result.cleaned_text
        pre_extracted_blocks = ocr_stage.stage_result.pre_extracted_blocks
        runtime_diagnostics = ocr_stage.stage_result.runtime_diagnostics
        ocr_diagnostics = ocr_stage.stage_result.diagnostics

        logger.info("image pipeline started: pipeline_id=%s", pipeline_id)
        from app.features.import_ai_policy import apply_image_single_pass_policy

        pipeline_options = apply_image_single_pass_policy(
            options,
            enabled=bool(options.get("image_fast_mode", True)),
        )
        result = await run_image_pipeline_stage(
            ImagePipelineStage(
                pipeline_id=pipeline_id,
                source_file=source_file,
                subject=subject,
                subject_id=subject_id,
                options=pipeline_options,
                created_by=created_by,
                image_bytes=image_content,
                cleaned_text=raw_text,
                pre_extracted_blocks=pre_extracted_blocks,
                async_session=async_session,
                ensure_record=ckpt.ensure_pipeline_record,
                run_pipeline=run_pipeline,
            )
        )

        result, status = finalize_image_pipeline_result(
            ImageCompletionRequest(
                pipeline_id=pipeline_id,
                result=result,
                cleaned_text=raw_text,
                raw_ocr_text=raw_ocr_text,
                ocr_diagnostics=ocr_diagnostics,
                runtime_diagnostics=runtime_diagnostics,
                classify_result=_classify_image_pipeline_result,
            )
        )
        await persist_image_completion(
            ImageCompletionPersistence(
                pipeline_id=pipeline_id,
                source_file=source_file,
                result=result,
                status=status,
                async_session=async_session,
                get_status=_get_image_pipeline_status,
                set_status=_set_image_pipeline_status,
                update_record=ckpt.update_pipeline_status,
                log_event=log_event,
            )
        )
    except Exception as exc:
        logger.exception(
            "image pipeline failed: pipeline_id=%s file=%s", pipeline_id, source_file
        )
        log_event(
            logger,
            "import.background.error",
            level="error",
            pipeline_id=pipeline_id,
            source_type="image",
            source_file=source_file,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
        )
        capture_exception(
            exc,
            tags={
                "pipeline_id": pipeline_id,
                "source_file": source_file,
                "stage": "ocr",
            },
        )
        from app.features import pipeline_checkpoint as ckpt

        await persist_image_failure(
            ImageFailurePersistence(
                pipeline_id=pipeline_id,
                source_file=source_file,
                exc=exc,
                async_session=async_session,
                fail_pipeline=_fail_image_pipeline,
                update_record=ckpt.update_pipeline_status,
            )
        )
        raise
    finally:
        await _release_pipeline_reservation(pipeline_id)
        if image_path and os.path.exists(image_path):
            try:
                os.unlink(image_path)
            except OSError as e:
                logger.warning("Failed to delete image tmp file %s: %s", image_path, e)


async def _run_pipeline_with_db(
    pipeline_id: str,
    file_path: str,
    source_type: str,
    source_file: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
    created_by: str | None = None,
    source_sha256: str | None = None,
) -> None:
    """后台任务包装器：创建独立 DB 会话并执行流水线。

    接收已写在磁盘上的临时文件路径，直接使用。完成后清理。
    """
    import traceback

    bind_log_context(
        trace_id=options.get("_trace_id"),
        request_id=options.get("_request_id"),
        pipeline_id=pipeline_id,
        source_type=source_type,
        source_file=source_file,
    )

    try:
        await execute_import_background(
            ImportBackgroundExecutionRequest(
                pipeline_id=pipeline_id,
                file_path=file_path,
                source_type=source_type,
                source_file=source_file,
                subject=subject,
                subject_id=subject_id,
                options=options,
                created_by=created_by,
                source_sha256=source_sha256,
                async_session=async_session,
                run_background=run_pipeline_background,
                logger=logger,
            )
        )
    except Exception as exc:
        logger.error(
            "Background task for pipeline %s crashed: %s\n%s",
            pipeline_id,
            exc,
            traceback.format_exc(),
        )
        log_event(
            logging.getLogger("postgraduate-ai"),
            "import.background.error",
            level="error",
            pipeline_id=pipeline_id,
            source_type=source_type,
            source_file=source_file,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
        )
        await record_background_pipeline_failure(
            pipeline_id=pipeline_id,
            source_type=source_type,
            source_file=source_file,
            exc=exc,
            async_session=async_session,
            set_pipeline_store=_set_pipeline_store,
            capture_exception=capture_exception,
        )
        raise
    finally:
        await _release_pipeline_reservation(pipeline_id)
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except OSError as e:
                logger.warning(
                    "Failed to delete pipeline tmp file %s: %s", file_path, e
                )


async def get_pipeline_status(
    pipeline_id: str, db: AsyncSession
) -> PipelineStatusResponse:
    """查询流水线执行状态。"""
    status = await _orchestrator_get_pipeline_status(pipeline_id, db=db)
    if status is None:
        status = await _get_image_pipeline_status(pipeline_id)
    if status is None:
        raise ValueError("流水线不存在")
    return PipelineStatusResponse(**status)


async def run_resume_background(
    pipeline_id: str,
    file_path: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
) -> None:
    """Background wrapper：单独 DB 会话跑 resume，结束后无条件清理 tmp 文件。"""
    bind_log_context(
        trace_id=options.get("_trace_id"),
        request_id=options.get("_request_id"),
        pipeline_id=pipeline_id,
    )
    try:
        async with async_session() as db:
            await resume_pipeline_background(
                pipeline_id=pipeline_id,
                file_path=file_path,
                subject=subject,
                subject_id=subject_id,
                options=options,
                db=db,
            )
    except Exception as exc:
        logger.exception("resume pipeline %s failed", pipeline_id)
        try:
            from app.features import pipeline_checkpoint as ckpt

            async with async_session() as db:
                await ckpt.update_pipeline_status(
                    db,
                    pipeline_id,
                    status="failed",
                    error_message=str(exc)[:4000],
                    finished=True,
                )
        except Exception:
            logger.exception(
                "Failed to persist resume pipeline failure: %s", pipeline_id
            )
        raise
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except OSError as e:
                logger.warning("Failed to delete resume tmp file %s: %s", file_path, e)
