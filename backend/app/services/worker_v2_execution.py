"""Run one v2 handler with fencing and failure-preserving resource cleanup."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.worker_v2_dispatch import dispatch_v2_task
from app.services.worker_v2_state import WorkerTaskState


async def run_v2_task(
    task: Any,
    *,
    namespace: dict[str, Any],
    set_context: Callable[..., Any],
    clear_context: Callable[..., None],
) -> None:
    state = await prepare_v2_task(task, namespace, set_context)
    primary: BaseException | None = None
    try:
        await dispatch_v2_task(state)
    except BaseException as error:
        primary = error
        raise
    finally:
        await cleanup_v2_resources(state, clear_context, primary)
    await verify_post_execution_fence(state)


async def prepare_v2_task(
    task: Any, namespace: dict[str, Any], set_context: Callable[..., Any]
) -> WorkerTaskState:
    await namespace["_check_worker_version_compatibility"](task)
    task_type = task.task_type
    payload = task.payload
    pipeline_id = payload.get("pipeline_id", task.task_id)
    fence_record_id: str = ""
    if task_type in (
        namespace["TASK_TYPE_IMPORT_PIPELINE"],
        namespace["TASK_TYPE_IMAGE_PIPELINE"],
        namespace["TASK_TYPE_EXCEL_PIPELINE"],
        namespace["TASK_TYPE_RESUME_PIPELINE"],
        namespace["TASK_TYPE_ADMIN_RESUME"],
    ):
        fence_record_id = pipeline_id
    elif task_type == namespace["TASK_TYPE_BATCH_IMAGE"]:
        fence_record_id = payload.get("job_id", "")
    namespace["logger"].info(
        "Worker v2 processing: type=%s task_id=%s pipeline_id=%s gen=%d",
        task_type,
        task.task_id,
        pipeline_id,
        task.generation,
    )
    if fence_record_id and task_type in namespace["_FENCING_TASK_TYPES"]:
        await namespace["_init_fencing_for_task"](task, fence_record_id, task_type)
    fence_token = None
    if fence_record_id and task_type in namespace["_FENCING_TASK_TYPES"]:
        fence_token = set_context(
            task_id=task.task_id, owner_token=task.owner_token, generation=task.generation
        )
    return WorkerTaskState(
        task, task_type, payload, pipeline_id, fence_record_id, namespace, fence_token
    )


async def cleanup_v2_resources(
    state: WorkerTaskState,
    clear_context: Callable[..., None],
    primary: BaseException | None,
) -> None:
    first_error = primary
    for work_path in state.staging_work_copies:
        try:
            await state.namespace["async_cleanup_work_copy"](work_path)
        except BaseException as error:
            first_error = retain_cleanup_failure(first_error, error)
    try:
        if state.fence_token is not None:
            clear_context(state.fence_token)
    except BaseException as error:
        first_error = retain_cleanup_failure(first_error, error)
    if primary is None and first_error is not None:
        raise first_error


def retain_cleanup_failure(primary: BaseException | None, error: BaseException) -> BaseException:
    if primary is None:
        return error
    try:
        BaseException.add_note(primary, f"v2 worker cleanup also failed ({type(error).__name__})")
    except BaseException:
        # A broken diagnostic annotation must not interrupt remaining cleanup.
        pass
    return primary


async def verify_post_execution_fence(state: WorkerTaskState) -> None:
    if state.fence_record_id and state.task_type in state.namespace["_FENCING_TASK_TYPES"]:
        from app.core.database import async_session
        from app.services.db_fencing import (
            FENCING_TABLES,
            FencingRejectedError,
            conditional_update_with_fencing,
        )

        table_entry = FENCING_TABLES.get(state.task_type)
        if table_entry is not None:
            model_class, _id_col = table_entry
            try:
                async with async_session() as db:
                    ok = await conditional_update_with_fencing(
                        db=db,
                        model_class=model_class,
                        record_id=state.fence_record_id,
                        expected_task_id=state.task.task_id,
                        expected_generation=state.task.generation,
                        expected_owner_token=state.task.owner_token,
                        execution_status="completed",
                    )
                    if not ok:
                        await db.rollback()
                        raise FencingRejectedError(
                            f"Post-execution fence lost: "
                            f"model={model_class.__name__} id={state.fence_record_id} "
                            f"task_id={state.task.task_id} gen={state.task.generation}"
                        )
                    await db.commit()
            except FencingRejectedError:
                raise
            except Exception as e:
                state.namespace["logger"].warning(
                    "Post-execution fence check failed (non-fatal): task_id=%s error=%s",
                    state.task.task_id,
                    e,
                )
