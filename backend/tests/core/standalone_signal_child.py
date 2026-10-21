"""Run a real CLI entry with external ports isolated for parent-only signals."""

import json
import os
import runpy
import socket
from pathlib import Path

from pytest import MonkeyPatch

from app.core import bootstrap, runtime_task_registry
from tests.core.standalone_role_ports import (
    RolePorts,
    install_common_ports,
    install_scheduler_ports,
    install_worker_ports,
)


def install_child_ports(patch, root, state):
    for name, value in {
        "APP_ENV": "test", "PROCESS_ROLE": "synthetic-prior", "WORKER_CONCURRENCY": 2,
        "WORKER_SHUTDOWN_GRACE_SEC": 1, "WORKER_SCRATCH_DIR": str(root / "scratch"),
        "STAGING_STORAGE_DIR": str(root / "staging"),
    }.items():
        patch.setattr(bootstrap.settings, name, value)
    patch.setattr(socket.socket, "connect", state.forbid_network)
    patch.setattr(socket.socket, "connect_ex", state.forbid_network)
    patch.setattr(bootstrap, "logger", state.logger)
    patch.setattr(runtime_task_registry, "logger", state.logger)
    for name, label in [
        ("run_token_cleanup", "token"), ("run_staging_cleanup", "staging"),
        ("run_export_processor_loop", "export"), ("run_export_cleanup", "export_cleanup"),
    ]:
        patch.setattr(bootstrap, name, lambda *args, label=label: state.loop(label))
    install_common_ports(patch, state)
    install_worker_ports(patch, state)
    install_scheduler_ports(patch, state)


def run_child():
    root, role = Path(os.environ["SIGNAL_TEST_ROOT"]), os.environ["SIGNAL_TEST_ROLE"]
    state = RolePorts()
    registry_type = runtime_task_registry.TaskRegistry
    install_signals = bootstrap.install_role_signal_handlers

    def registry():
        instance = registry_type()
        state.registries.append(instance)
        return instance

    def signals(event, logger):
        install_signals(event, logger)
        (root / "ready").write_text("handlers-installed")

    with MonkeyPatch.context() as patch:
        install_child_ports(patch, root, state)
        patch.setattr(runtime_task_registry, "TaskRegistry", registry)
        patch.setattr(bootstrap, "install_role_signal_handlers", signals)
        runpy.run_module("app." + role + "_main", run_name="__main__")
        assert bootstrap.settings.PROCESS_ROLE == os.environ["PROCESS_ROLE"] == role
        assert not state.network
        assert len(state.registries) == 1
        assert all(item._task.done() for item in state.registries[0]._tasks)
        assert state.logger.info.call_args_list.count(
            (("Received shutdown signal, initiating graceful shutdown",), {}),
        ) == 1
        (root / "result.json").write_text(json.dumps({
            "events": state.events,
            "tasks": [item.name for item in state.registries[0]._tasks],
            "role": role,
        }))


if __name__ == "__main__":
    run_child()
