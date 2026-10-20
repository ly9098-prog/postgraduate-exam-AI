"""Resolve the standalone policies without constructing configuration."""

from types import SimpleNamespace

from app.core import standalone_runtime_policy


def standalone_policies():
    return SimpleNamespace(
        module=standalone_runtime_policy,
        guard=standalone_runtime_policy.reject_standalone_http_launch,
        scratch=standalone_runtime_policy.ensure_worker_scratch_directory,
        reporter=standalone_runtime_policy.create_standalone_failure_reporter,
    )
