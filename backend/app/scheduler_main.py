"""Scheduler entry point — periodic background tasks (no HTTP listener).

Usage::

    python -m app.scheduler_main

Sets PROCESS_ROLE=scheduler and runs only background scheduling/runtime work:
refresh-token cleanup, staging cleanup, audit-log cleanup, recommendation-metrics
aggregation, export processing/cleanup, outbox reconciliation and async-task
health monitoring. Does NOT start an HTTP server or pipeline worker.

All scheduled tasks acquire a distributed Redis lock before execution.
If the lock cannot be acquired, the task is skipped (another instance
is already running it).
"""

import os

os.environ["PROCESS_ROLE"] = "scheduler"

from app.core.bootstrap import run_role

if __name__ == "__main__":
    run_role("scheduler")
