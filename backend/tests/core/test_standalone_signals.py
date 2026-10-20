"""Send OS signals only to fresh, isolated role CLI children."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.core.test_standalone_role_lifecycle import (
    COMMON_STOP,
    SCHEDULER_TASKS,
    WORKER_TASKS,
)

BACKEND = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal delivery requires a POSIX child process")
@pytest.mark.parametrize("role", ["worker", "scheduler"])
@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_real_role_cli_signal_runs_ordered_shutdown_and_exits_zero(tmp_path, role, sig):
    environment = {
        "PATH": os.defpath, "PYTHONPATH": str(BACKEND), "APP_ENV": "test",
        "DEPLOYMENT_PROFILE": "local_import", "APP_SECRET": "synthetic-signal-test-secret-12345678",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:", "REDIS_URL": "", "SENTRY_DSN": "",
        "OCR_ENABLED": "false", "STAGING_STORAGE_DIR": str(tmp_path / "staging"),
        "SIGNAL_TEST_ROOT": str(tmp_path), "SIGNAL_TEST_ROLE": role,
    }
    with (tmp_path / "stdout").open("w") as stdout, (tmp_path / "stderr").open("w") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-m", "tests.core.standalone_signal_child"],
            cwd=tmp_path, env=environment, stdout=stdout, stderr=stderr,
        )
        try:
            deadline = time.monotonic() + 15
            while not (tmp_path / "ready").exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            assert process.poll() is None and (tmp_path / "ready").exists(), (tmp_path / "stderr").read_text()
            process.send_signal(sig)
            assert process.wait(timeout=15) == 0, (tmp_path / "stderr").read_text()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["role"] == role
    assert result["tasks"] == (WORKER_TASKS if role == "worker" else SCHEDULER_TASKS)
    assert [event for event in result["events"] if event in COMMON_STOP] == COMMON_STOP
    assert any(event.startswith("end:") for event in result["events"])
