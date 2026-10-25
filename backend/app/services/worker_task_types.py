"""Task types consumed by the standalone worker role.

Both reapers cover all dispatcher task types plus AI prewarm. Prewarm has its
own execution loop, but its durable lease still needs reaping if that worker
crashes; therefore it is included only in the reaper list.
"""

from __future__ import annotations

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
