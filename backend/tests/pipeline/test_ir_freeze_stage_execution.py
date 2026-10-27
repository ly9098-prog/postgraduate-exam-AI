"""Real synchronous stages retain bindings through async single-pass completion."""

import asyncio
from types import SimpleNamespace

import pytest

from tests.pipeline.ir_freeze_binding_support import (
    OPTIONS,
    isolated_runtime,
    source_blocks,
)
from tests.pipeline.ir_freeze_safety_support import freeze_sources


@pytest.fixture
def binding_runtime(monkeypatch, tmp_path):
    yield from isolated_runtime(monkeypatch, tmp_path)


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
@pytest.mark.parametrize("count", [1, 2])
def test_real_stage_threads_and_completion_forward_verified_plan(
    binding_runtime, monkeypatch, mode, count
):
    from app.features.pipeline_single_pass_execution import complete_pass_stage
    from app.features.pipeline_stage_completion import complete_stage_data

    module = binding_runtime.pipeline_module
    pipeline, blocks, _, _ = freeze_sources(
        binding_runtime, monkeypatch, source_blocks(count), mode=mode
    )
    state = SimpleNamespace(
        data={"normalized_blocks": blocks, "source_type": "pdf", "import_mode": "exam"},
        chunked=True,
    )
    values = {
        "isinstance": isinstance,
        "dict": dict,
        "len": len,
        "logger": module.logger,
        "_update_stage_metrics": module._update_stage_metrics,
        "complete_stage_data": complete_stage_data,
    }

    async def execute():
        for name, method in (
            ("structure_freeze", pipeline._run_structure_freeze),
            ("split", pipeline._run_split),
        ):
            state.current_name = name
            state.current_stage = module.PipelineStage(name, method)
            await complete_pass_stage(state, ports=values.__getitem__)
            assert state.current_stage.status == "completed"
        return state.data

    data = asyncio.run(execute())
    assert data["freeze_block_binding"]["version"] == 1
    assert [question["option_lines"] for question in data["raw_questions"]] == list(
        OPTIONS[:count]
    )
    assert all(question["is_frozen"] for question in data["raw_questions"])
    assert data["freeze_binding_diagnostics"]["accepted_questions"] == count
    assert data["split_count"] == count
    assert "split_quality" in data
