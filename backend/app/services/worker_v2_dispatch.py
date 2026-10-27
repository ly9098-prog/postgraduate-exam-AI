"""Dispatch v2 task types in the existing compatibility order."""

from __future__ import annotations

from app.services.worker_v2_aux_handlers import (
    run_batch_image_handler,
    run_formula_handler,
)
from app.services.worker_v2_pipeline_handlers import (
    run_admin_resume_handler,
    run_excel_handler,
    run_image_handler,
    run_import_handler,
    run_resume_handler,
)
from app.services.worker_v2_state import WorkerTaskState


async def dispatch_v2_task(state: WorkerTaskState) -> None:
    if state.task_type == state.namespace["TASK_TYPE_IMPORT_PIPELINE"]:
        await run_import_handler(state)
    elif state.task_type == state.namespace["TASK_TYPE_IMAGE_PIPELINE"]:
        await run_image_handler(state)
    elif state.task_type == state.namespace["TASK_TYPE_EXCEL_PIPELINE"]:
        await run_excel_handler(state)
    elif state.task_type == state.namespace["TASK_TYPE_RESUME_PIPELINE"]:
        await run_resume_handler(state)
    elif state.task_type == state.namespace["TASK_TYPE_ADMIN_RESUME"]:
        await run_admin_resume_handler(state)
    elif state.task_type == state.namespace["TASK_TYPE_ANSWER_PROJECTION"]:
        await state.namespace["_process_answer_projection_task"](state.task)
    elif state.task_type == state.namespace["TASK_TYPE_ERROR_DIAGNOSIS"]:
        await state.namespace["_process_error_diagnosis_task"](state.task)
    elif state.task_type == state.namespace["TASK_TYPE_FORMULA_BATCH"]:
        await run_formula_handler(state)
    elif state.task_type == state.namespace["TASK_TYPE_BATCH_IMAGE"]:
        await run_batch_image_handler(state)
    else:
        state.namespace["logger"].warning(
            "Unknown task type %s — marking as dead-letter: task_id=%s",
            state.task_type,
            state.task.task_id,
        )
        state.task.max_retries = 0
        raise ValueError(f"unknown_task_type: {state.task_type}")
