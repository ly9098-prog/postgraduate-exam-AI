"""Original-module type ports remain live in PP fallback and table filtering."""

import pytest

from app.features import pipeline_orchestrator as module
from tests.pipeline.vl_rebuild_support import execute, fail_at, make_harness


def test_pp_exception_type_is_resolved_in_original_namespace(monkeypatch):
    harness = make_harness(monkeypatch)
    failure = ValueError("synthetic PP failure")
    monkeypatch.setattr(module, "Exception", KeyError, raising=False)
    fail_at(harness, "pp", failure)
    with pytest.raises(ValueError) as caught:
        execute(harness)
    assert caught.value is failure
    assert "warning" not in harness.events and "fix" not in harness.events


def test_table_dict_type_is_resolved_in_original_namespace(monkeypatch):
    harness = make_harness(monkeypatch)
    monkeypatch.setattr(module, "dict", tuple, raising=False)
    output = execute(harness)
    assert output[0]["text"] == "VL:A B C"
    assert output[0]["vl_layout_blocks"] == []
