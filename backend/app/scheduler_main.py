"""Scheduler entry point — periodic background tasks (no HTTP listener).

Usage::

    python -m app.scheduler_main

Sets PROCESS_ROLE=scheduler and runs only periodic tasks:
token cleanup, staging cleanup, pomodoro scheduler, audit cleanup,
export processor. Does NOT start an HTTP server.

All scheduled tasks acquire a distributed Redis lock before execution.
If the lock cannot be acquired, the task is skipped (another instance
is already running it).
"""

import os

from app.core.bootstrap import run_role

os.environ.setdefault("PROCESS_ROLE", "scheduler")

if __name__ == "__main__":
    run_role("scheduler")
