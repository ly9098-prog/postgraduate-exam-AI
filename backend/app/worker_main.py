"""Worker entry point — background task processor (no HTTP listener).

Usage::

    python -m app.worker_main

Sets PROCESS_ROLE=worker and runs only the task dispatcher, reaper,
and AI prewarm worker. Does NOT start an HTTP server.

The worker process should NOT be exposed to public networks.
"""

import os

from app.core.bootstrap import run_role

os.environ.setdefault("PROCESS_ROLE", "worker")

if __name__ == "__main__":
    run_role("worker")
