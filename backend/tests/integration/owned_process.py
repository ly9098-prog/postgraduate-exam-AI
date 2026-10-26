"""Minimal environments and birth-checked child ownership for Linux service tests."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


def private_environment(directory=None):
    environment = {"PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8"}
    if directory is not None:
        environment.update(HOME=str(directory), TMPDIR=str(directory))
    return environment


def spawn_owned(command, *, log, directory, environment=None):
    process = subprocess.Popen(
        command,
        cwd=directory,
        stdout=log,
        stderr=log,
        start_new_session=True,
        env=environment if environment is not None else private_environment(directory),
    )
    process._owned_session_id = process.pid
    identity = _identity(process.pid)
    assert identity is not None
    process._owned_children = {process.pid: identity[1]}
    return process


def _identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[1]), fields[19], fields[0]  # parent, birth tick, state
    except (OSError, ValueError, IndexError):
        return None


def capture_owned_children(process):
    if getattr(process, "_owned_session_id", None) != process.pid:
        raise RuntimeError("Refusing to signal an unowned process group")
    known = process._owned_children
    snapshot = {
        int(path.parent.name): identity
        for path in Path("/proc").glob("[0-9]*/stat")
        if (identity := _identity(int(path.parent.name))) is not None
    }
    parents = {
        pid
        for pid, birth in known.items()
        if pid in snapshot and snapshot[pid][1] == birth
    }
    while True:
        added = {
            pid
            for pid, identity in snapshot.items()
            if identity[0] in parents and pid not in parents
        }
        if not added:
            break
        known.update({pid: snapshot[pid][1] for pid in added})
        parents.update(added)
    return sorted(pid for pid in parents if snapshot[pid][2] != "Z")


def _signal_owned(process, pid, sig):
    # pidfd prevents PID reuse between the birth check and delivery.
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        identity = _identity(pid)
        if identity and identity[1] == process._owned_children[pid]:
            signal.pidfd_send_signal(descriptor, sig)
    except ProcessLookupError:
        pass
    finally:
        os.close(descriptor)


def stop_owned_group(process):
    # PostgreSQL backends create their own sessions; track the actual child tree.
    for _ in range(3):
        members = capture_owned_children(process)
        for pid in members:
            _signal_owned(process, pid, signal.SIGSTOP)
        if capture_owned_children(process) == members:
            break
    for pid in capture_owned_children(process):
        _signal_owned(process, pid, signal.SIGKILL)
    process.wait(timeout=5)
    deadline = time.monotonic() + 5
    while capture_owned_children(process) and time.monotonic() < deadline:
        time.sleep(0.02)
    remaining = capture_owned_children(process)
    if remaining:
        raise RuntimeError(f"Private process group still running: {remaining}")
