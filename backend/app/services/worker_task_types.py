"""Task types consumed by the standalone worker role.

Both reapers cover all dispatcher task types plus AI prewarm. Prewarm has its
own execution loop, but its durable lease still needs reaping if that worker
crashes; therefore it is included only in the reaper list.
"""

from __future__ import annotations

from app.services.ai.prewarm_transition import dead_retry_budget

_DEAD_RETRY_BUDGET_POLICIES = {
    "prewarm_analysis": dead_retry_budget,
}


def dead_retry_budget_for_task(task_type: str, task_data: dict) -> int | None:
    policy = _DEAD_RETRY_BUDGET_POLICIES.get(task_type)
    return policy(task_data) if policy else None


DISPATCHER_TASK_TYPES = [
    "import_pipeline",
    "image_pipeline",
    "excel_pipeline",
    "resume_pipeline",
    "admin_resume",
    "batch_image",
    "formula_batch",
    "answer_projection",
    "error_diagnosis",
]

REAPER_TASK_TYPES = [
    *DISPATCHER_TASK_TYPES,
    "prewarm_analysis",
]
