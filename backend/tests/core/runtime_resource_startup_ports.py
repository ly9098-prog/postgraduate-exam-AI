"""Exercise the original startup blocks through isolated resource ports."""

import sys
from enum import StrEnum
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core import runtime_resource_startup


@pytest.fixture
def ports(monkeypatch):
    subject = runtime_resource_startup
    logger = Mock()
    monkeypatch.setattr(subject, "logger", logger)
    events, failures = [], {}

    class Profile(StrEnum):
        LOCAL_IMPORT = "local_import"
        CLOUD_API = "cloud_api"

    state = SimpleNamespace(profile=Profile.LOCAL_IMPORT, executors={}, events=events, failures=failures, logger=logger, subject=subject)

    def operation(name, result):
        def call(*args, **kwargs):
            events.append((name, args, kwargs))
            if name in failures:
                raise failures[name]
            return result()
        return call

    async def start():
        return operation("reconciler", lambda: None)()

    modules = {
        "app.core.deployment_profile": SimpleNamespace(
            DeploymentProfile=Profile, detect_deployment_profile=operation("profile", lambda: state.profile),
        ),
        "app.core.executors": SimpleNamespace(init_executors_for_role=operation("executors", lambda: state.executors)),
        "app.core.executor_registry": SimpleNamespace(init_executor_registry=operation("registry", lambda: None)),
        "app.core.resource_guard": SimpleNamespace(resource_guard=SimpleNamespace(start_orphan_reconciler=start)),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    state.modules = modules
    return state
