"""Generation token for safe export lifecycle management.

Ensures that timed-out or cancelled tasks don't continue to upload files
or modify the database.  Inspired by a cancellation token pattern.
"""

from __future__ import annotations


class GenerationToken:
    """A per-task token that tracks whether generation is still authorized.

    Usage::

        token = GenerationToken()
        try:
            async with asyncio.timeout(TIMEOUT):
                await process_task(db, task_id, exporter, token=token)
        except TimeoutError:
            token.invalidate()
            # process_task will have checked token.is_active() before
            # uploading or marking the task completed.

    Thread-safety: ``is_active`` / ``invalidate`` are plain attribute
    accesses (atomic in CPython) and do not need a lock.
    """

    __slots__ = ("_active",)

    def __init__(self) -> None:
        self._active = True

    def is_active(self) -> bool:
        """Return ``True`` if generation is still authorised."""
        return self._active

    def invalidate(self) -> None:
        """Revoke authorisation.  Further uploads / DB writes are blocked."""
        self._active = False
