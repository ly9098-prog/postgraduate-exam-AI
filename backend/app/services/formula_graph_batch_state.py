"""Process-local formula batch status shared by producers and execution."""

import asyncio

jobs: dict[str, dict] = {}
lock = asyncio.Lock()


async def get_batch_status(job_id: str) -> dict | None:
    """Return the existing in-process status object, if present."""
    return jobs.get(job_id)


def _cleanup_old_jobs(max_keep: int = 10) -> None:
    """Remove oldest completed jobs beyond max_keep."""
    completed = [
        (jid, j)
        for jid, j in jobs.items()
        if j.get("status") in ("completed", "partial_failed", "failed")
    ]
    if len(completed) > max_keep:
        completed.sort(key=lambda x: x[1].get("finished_at", ""))
        for jid, _ in completed[: len(completed) - max_keep]:
            jobs.pop(jid, None)
