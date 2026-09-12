"""Review Artifact Deployment Profile — Verify artifact includes profile info."""
from __future__ import annotations

from app.features.control_plane import PipelineExecutionContext


def test_artifact_contains_profile():
    ctx = PipelineExecutionContext(deployment_profile="local_import")
    serialized = ctx.to_dict()
    assert serialized["deployment_profile"] == "local_import"


def test_artifact_cloud_profile():
    ctx = PipelineExecutionContext(deployment_profile="cloud_api")
    serialized = ctx.to_dict()
    assert serialized["deployment_profile"] == "cloud_api"


def test_artifact_runtime_caps():
    ctx = PipelineExecutionContext(
        deployment_profile="cloud_api",
        runtime_capabilities={"gpu_available": False, "cpu_count": 2},
    )
    serialized = ctx.to_dict()
    assert "runtime_capabilities" in serialized
    assert serialized["runtime_capabilities"]["gpu_available"] is False
