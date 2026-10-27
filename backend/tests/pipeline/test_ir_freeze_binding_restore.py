"""Plans retain independent content through JSON and real artifact round trips."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from tests.pipeline.ir_freeze_binding_support import (
    OPTIONS,
    isolated_runtime,
    source_blocks,
)
from tests.pipeline.ir_freeze_safety_support import (
    assert_bound,
    assert_unbound,
    freeze_sources,
    reseal,
    split_frozen,
)


@pytest.fixture
def binding_runtime(monkeypatch, tmp_path):
    yield from isolated_runtime(monkeypatch, tmp_path)


@pytest.mark.parametrize("mode", ["ir", "ir_canary"])
def test_json_roundtrip_keeps_options_and_source_ownership(
    binding_runtime, monkeypatch, mode
):
    pipeline, blocks, frozen, _ = freeze_sources(
        binding_runtime, monkeypatch, source_blocks(2), mode=mode
    )
    restored = {
        "freeze_mode": mode,
        "freeze_block_binding": json.loads(json.dumps(frozen["freeze_block_binding"])),
    }
    restored_blocks = [
        {k: v for k, v in block.items() if k != "_document_ir"} for block in blocks
    ]
    result = split_frozen(pipeline, json.loads(json.dumps(restored_blocks)), restored)
    assert_bound(result, list(OPTIONS))


def test_plan_options_are_independent_of_raw_mutable_ir_entries(
    binding_runtime, monkeypatch
):
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch)
    before = copy.deepcopy(frozen["freeze_block_binding"])
    for entries in frozen["frozen_option_registry_ir"].values():
        entries[0].normalized_text = "changed-after-freeze"
        entries.clear()
    assert frozen["freeze_block_binding"] == before
    assert_bound(split_frozen(pipeline, blocks, frozen), [OPTIONS[0]])


@pytest.mark.parametrize("mutation", ["options", "source", "generation"])
def test_modified_plan_checksum_is_rejected(binding_runtime, monkeypatch, mutation):
    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch)
    plan = frozen["freeze_block_binding"]
    if mutation == "options":
        plan["regions"][0]["options"]["A"] = "tampered"
    elif mutation == "source":
        plan["sources"][0]["block_index"] += 1
    else:
        plan["generation"] = "different-generation"
    result = split_frozen(pipeline, blocks, frozen)
    assert_unbound(result, reason="invalid_source_binding")
    assert result["raw_questions"][0]["option_lines"] == OPTIONS[0]


@pytest.mark.parametrize(
    "mutation", ["duplicate", "index", "region", "options", "version"]
)
def test_malformed_resealed_plans_are_not_consumed(
    binding_runtime, monkeypatch, mutation
):
    pipeline, blocks, frozen, _ = freeze_sources(
        binding_runtime, monkeypatch, source_blocks(2)
    )
    plan = frozen["freeze_block_binding"]
    if mutation == "duplicate":
        plan["regions"][1]["source_index"] = plan["regions"][0]["source_index"]
    elif mutation == "index":
        plan["regions"][0]["source_index"] = -1
    elif mutation == "region":
        plan["regions"][1]["region_id"] = plan["regions"][0]["region_id"]
    elif mutation == "options":
        plan["regions"][0]["options"] = {"A": ["invalid"]}
    else:
        plan["version"] = True
    reseal(plan)
    result = split_frozen(pipeline, blocks, frozen)
    reason = (
        "invalid_frozen_options" if mutation == "options" else "invalid_source_binding"
    )
    assert_unbound(result, reason=reason)


def test_real_artifact_restores_verified_plan_and_rejects_old_split_version(
    binding_runtime, monkeypatch, tmp_path
):
    from app.features import pipeline_artifacts as artifacts

    pipeline, blocks, frozen, _ = freeze_sources(binding_runtime, monkeypatch)
    monkeypatch.setenv("PIPELINE_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    data = {
        "blocks": [{k: v for k, v in blocks[0].items() if k != "_document_ir"}],
        "freeze_mode": "ir",
        "freeze_block_binding": frozen["freeze_block_binding"],
    }
    path = artifacts.save_artifact("source-binding-restore", "split", data)
    assert path is not None
    assert artifacts.check_artifact_compatibility(
        "source-binding-restore", "split"
    ) == (True, "")
    restored = artifacts.load_artifact("source-binding-restore", "split")
    assert_bound(split_frozen(pipeline, restored.pop("blocks"), restored), [OPTIONS[0]])
    with monkeypatch.context() as old_version:
        old_version.setattr(artifacts, "_PIPELINE_SCHEMA_VERSION", "2")
        previous = artifacts._build_pipeline_fingerprint()
    wrapped = json.loads(Path(path).read_text())
    wrapped["pipeline_version"] = (
        previous + "_cfg" + artifacts._build_config_fingerprint()
    )
    Path(path).write_text(json.dumps(wrapped))
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    compatible, reason = artifacts.check_artifact_compatibility(
        "source-binding-restore", "split"
    )
    assert not compatible
    assert "version" in reason.lower()
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
