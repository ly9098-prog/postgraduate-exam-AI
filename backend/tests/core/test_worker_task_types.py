from app.services.worker_task_types import DISPATCHER_TASK_TYPES, REAPER_TASK_TYPES


def test_dispatcher_task_types_are_the_exact_worker_contract() -> None:
    assert DISPATCHER_TASK_TYPES == [
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


def test_reaper_covers_dispatcher_and_prewarm_leases() -> None:
    assert REAPER_TASK_TYPES[: len(DISPATCHER_TASK_TYPES)] == DISPATCHER_TASK_TYPES
    assert REAPER_TASK_TYPES[len(DISPATCHER_TASK_TYPES):] == ["prewarm_analysis"]
    assert len(REAPER_TASK_TYPES) == len(set(REAPER_TASK_TYPES))


def test_dispatcher_does_not_claim_prewarm_from_its_worker() -> None:
    assert "prewarm_analysis" not in DISPATCHER_TASK_TYPES
