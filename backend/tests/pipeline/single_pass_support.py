"""Deterministic ports for the real single-pass stage execution loop."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from app.features import pipeline_orchestrator as orchestrator
from app.features.import_mode import ImportMode
from app.features.pipeline_definition import PipelineDefinition

STAGE_NAMES = PipelineDefinition.stage_names()


def _stage_runner(harness, name):
    async def run(**data):
        harness.calls.append(name)
        harness.inputs[name] = dict(data)
        harness.trace.append(("run", name))
        if harness.failure_at == name:
            raise harness.failure
        return harness.outputs.get(name, {})

    return run


def _install_effect_ports(monkeypatch, harness):
    async def checkpoint(pipeline_id, **values):
        harness.checkpoints.append(deepcopy(values))
        harness.trace.append(("checkpoint", values["current_stage"]))

    async def clear(pipeline_id):
        harness.trace.append(("clear", pipeline_id))

    def save(pipeline_id, name, data):
        harness.artifacts.append((name, dict(data)))
        harness.trace.append(("artifact", name))

    def stats(data, stages):
        harness.final_data = dict(data)
        return {"observed": True}

    monkeypatch.setattr(orchestrator, "_write_stage_checkpoint", checkpoint)
    monkeypatch.setattr(orchestrator, "_clear_stage_checkpoint", clear)
    monkeypatch.setattr(orchestrator, "_save_stage_artifact", save)
    monkeypatch.setattr(orchestrator, "_build_stats", stats)
    monkeypatch.setattr(orchestrator, "_build_diagnostics", lambda *_: {})
    monkeypatch.setattr(orchestrator, "_build_quality_report", lambda *_: {})
    monkeypatch.setattr(orchestrator, "_list_artifacts", lambda *_: ["synthetic"])
    monkeypatch.setattr(orchestrator, "_log_routing_stability", lambda *_: None)
    monkeypatch.setattr(orchestrator, "_update_stage_metrics", lambda *_: None)
    for attr, label in (
        ("_save_completed_marker", "completed"),
        ("_save_failed_marker", "failed"),
    ):
        monkeypatch.setattr(
            orchestrator,
            attr,
            lambda pipeline_id, tag=label: harness.trace.append((tag, pipeline_id)),
        )


def make_harness(monkeypatch, *, failure_at=None, failure=None):
    harness = SimpleNamespace(
        calls=[],
        inputs={},
        trace=[],
        checkpoints=[],
        artifacts=[],
        final_data=None,
        failure_at=failure_at,
        failure=failure or RuntimeError("synthetic failure"),
        outputs={
            "extract": {"raw_blocks": [{"text": "synthetic"}]},
            "normalize_text": {"normalized_blocks": [{"text": "one"}, {"text": "two"}]},
            "split": {"raw_questions": [{"number": 1}]},
            "match": {"matched": [1], "unmatched": [2]},
            "normalize_schema": {"questions": [{"number": 1}]},
            "review": {"batch_id": "synthetic-batch", "review_new_hashes": ["hash"]},
        },
    )
    harness.pipeline = orchestrator.ImportPipeline()
    harness.pipeline.pipeline_id = "single-pass-contract"

    def build():
        harness.pipeline.stages = {
            name: orchestrator.PipelineStage(name, _stage_runner(harness, name))
            for name in STAGE_NAMES
        }

    monkeypatch.setattr(harness.pipeline, "_build_pipeline", build)
    _install_effect_ports(monkeypatch, harness)
    import app.evaluation.routing_metrics as routing
    import app.evaluation.split_quality as split_quality

    monkeypatch.setattr(
        routing, "build_routing_metrics", lambda *_: {"route": "synthetic"}
    )
    monkeypatch.setattr(
        split_quality, "evaluate_split_quality", lambda *_: {"quality": 1}
    )
    return harness


async def execute(harness, **overrides):
    arguments = {
        "file_content": b"synthetic input",
        "file_path": "/synthetic/input.pdf",
        "source_type": "pdf",
        "source_file": "input.pdf",
        "subject": "math",
        "subject_id": 7,
        "opts": {},
        "db": None,
        "shared": {
            "import_mode": ImportMode.AUTO,
            "strategy": object(),
            "watermark_patterns": [],
        },
        "progress_callback": None,
        "started_at": "synthetic-start",
        "page_images": {1: b"image"},
    }
    arguments.update(overrides)
    return await harness.pipeline._run_single_pass(**arguments)
