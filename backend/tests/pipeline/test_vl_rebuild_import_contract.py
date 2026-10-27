"""Local import timing, synchronous coroutine bridge and configuration fallback."""

import sys
from types import SimpleNamespace

import pytest

from app.features import pipeline_orchestrator as module
from tests.pipeline.vl_rebuild_support import execute, fail_at, make_harness, observe


@pytest.mark.parametrize("key", ["api_key", "api_base_url", "model_name"])
def test_configuration_read_failure_is_inside_fallback(monkeypatch, key):
    harness = make_harness(monkeypatch)
    error = RuntimeError(key)

    class Config(dict):
        def get(self, name, default=None):
            if name == key:
                raise error
            return super().get(name, default)

    assert execute(harness, vl_config=Config(api_key="synthetic")) is None
    assert harness.records["warning"] == [("VL_REBUILD failed: %s", error)]
    assert "construct_router" not in harness.events


def test_missing_token_warning_failure_is_inside_fallback(monkeypatch):
    harness = make_harness(monkeypatch)
    error = RuntimeError("warning")

    def fail_once(_):
        harness.hooks.pop("warning")
        raise error

    harness.hooks["warning"] = fail_once
    assert execute(harness, vl_config={"model_name": "synthetic"}) is None
    assert harness.records["warning"][-1] == ("VL_REBUILD failed: %s", error)


def test_local_ocr_is_imported_again_for_each_page(monkeypatch):
    harness = make_harness(monkeypatch)

    def next_pp(image):
        observe(harness, "next_pp", image)
        return "PP:A B"

    harness.hooks["pp"] = lambda _: monkeypatch.setitem(
        sys.modules, "app.services.ocr_service", SimpleNamespace(ocr_raw_text=next_pp)
    )
    assert len(execute(harness, file_path="/synthetic/input.pdf")) == 2
    assert harness.records["pp"] == [b"one"]
    assert harness.records["next_pp"] == [b"two"]


def test_profile_failure_precedes_local_ocr_import(monkeypatch):
    harness = make_harness(monkeypatch)
    error = RuntimeError("profile")
    fail_at(harness, "profile", error)
    monkeypatch.setitem(sys.modules, "app.services.ocr_service", None)
    assert execute(harness) is None
    assert harness.records["warning"] == [("VL_REBUILD failed: %s", error)]
    assert "pp" not in harness.events


def test_real_sync_bridge_consumes_router_coroutine(monkeypatch):
    bridge = module._run_coro_in_loop
    harness = make_harness(monkeypatch)
    router = sys.modules["app.features.ocr_fix.router"].OCRFixRouter

    async def fix(self, **arguments):
        observe(harness, "async_fix", arguments)
        return harness.result

    monkeypatch.setattr(router, "fix", fix)
    monkeypatch.setattr(module, "_run_coro_in_loop", bridge)
    assert execute(harness)[0]["text"] == "VL:A B C"
    assert len(harness.records["async_fix"]) == 1
    assert "run" not in harness.events


def test_harness_restores_original_global_bridge(monkeypatch):
    bridge = module._run_coro_in_loop
    with monkeypatch.context() as scoped:
        harness = make_harness(scoped)
        assert module._run_coro_in_loop is not bridge
        assert execute(harness)
    assert module._run_coro_in_loop is bridge


def test_entry_rejects_unexpected_keyword_arguments(monkeypatch):
    harness = make_harness(monkeypatch)
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        execute(harness, unexpected_vl_option=True)
    assert harness.events == []


def test_pdf_vl_result_text_follows_its_page_image(monkeypatch):
    harness = make_harness(monkeypatch)
    harness.results[b"two"] = SimpleNamespace(fixed_text="second page", metadata={})
    harness.options["second page"] = dict.fromkeys("ABCD", "second")
    output = execute(harness, file_path="/synthetic/input.pdf")
    assert [block["text"] for block in output] == ["VL:A B C", "second page"]
    assert [block["page"] for block in output] == [1, 2]
    assert output[0]["vl_layout_blocks"] == harness.layout[:3]
    assert output[1]["vl_layout_blocks"] == []
