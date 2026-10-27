"""PP/VL selection, original option merge and final recovery publication."""

from copy import deepcopy

import pytest

from tests.pipeline.vl_rebuild_support import execute, fail_at, make_harness


@pytest.mark.parametrize(
    "pp_count,vl_count,winner",
    [
        (0, 0, "VL"),
        (0, 2, "VL"),
        (1, 0, "PP"),
        (1, 1, "PP"),
        (1, 2, "VL"),
        (3, 2, "PP"),
        (3, 4, "VL"),
        (4, 5, "PP"),
        (5, 6, "PP"),
    ],
)
def test_option_count_thresholds_select_pp_or_vl_without_dropping_metadata(
    monkeypatch, pp_count, vl_count, winner
):
    h = make_harness(monkeypatch)
    h.pp[b"image"], h.result.fixed_text = "PP", "VL"
    h.options = {
        "PP": {str(i): str(i) for i in range(pp_count)},
        "VL": {str(i): str(i) for i in range(vl_count)},
    }
    before = deepcopy(h.layout)
    output = execute(h)
    assert output[0]["text"] == winner
    assert ("fix" in h.events) == (pp_count < 4)
    assert output[0]["vl_layout_blocks"] == (before[:3] if pp_count < 4 else [])
    if pp_count < 4:
        assert all(output[0]["vl_layout_blocks"][i] is h.layout[i] for i in range(3))
    assert h.layout == before


def test_cloud_profile_uses_vl_without_importing_local_ocr(monkeypatch):
    import sys

    h = make_harness(monkeypatch)
    h.cloud = True
    monkeypatch.setitem(sys.modules, "app.services.ocr_service", None)
    output = execute(h)
    assert output[0]["text"] == "VL:A B C"
    assert "pp" not in h.events and "fix" in h.events


@pytest.mark.parametrize("text", [None, ""])
def test_missing_vl_text_preserves_valid_pp_but_no_table_metadata(monkeypatch, text):
    h = make_harness(monkeypatch)
    if text is None:
        h.results[b"image"] = None
    else:
        h.result.fixed_text = text
    output = execute(h)
    assert output[0]["text"] == "PP:A B" and output[0]["vl_layout_blocks"] == []
    assert "repair" not in h.events


def test_unstructured_pp_without_vl_produces_no_blocks(monkeypatch):
    h = make_harness(monkeypatch)
    h.pp[b"image"] = "plain pp text"
    h.results[b"image"] = None
    assert execute(h) is None
    assert "recover" not in h.events and h.records["warning"][-1] == (
        "VL_REBUILD: no blocks produced",
    )


def test_repaired_candidate_without_options_does_not_gain_raw_vl_option_count(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    h.repaired = "plain repaired text"
    output = execute(h)
    assert output[0]["text"] == "PP:A B"
    assert h.records["repair"] == [("VL:A B C", "PP:A B", "")]
    assert h.records["detect"] == ["PP:A B", "plain repaired text"]
    assert "VL:A B C" not in h.records["extract"]


def test_original_options_are_appended_in_source_line_order_with_strict_prefix(
    monkeypatch,
):
    h = make_harness(monkeypatch)
    raw = "skip C) bad\n  D. original D\nC. original C\nC. duplicate C"
    h.options[raw] = {"A": "original A", "C": "original C", "D": "original D"}
    h.options["VL:A B C"] = {"A": "vA"}
    h.options["PP:A B"] = {"A": "pA"}
    output = execute(h, original_raw_text=raw)
    assert output[0]["text"] == "PP:A B\n  D. original D\nC. original C"
    assert h.options["PP:A B"] == {"A": "pA", "C": "original C", "D": "original D"}
    merges = [args for args in h.records["info"] if "merged option" in args[0]]
    assert [(args[2], args[3]) for args in merges] == [("D", 2), ("C", 3)]
    assert h.records["recover"][0] == (output[0]["text"], "PP:A B", raw)


@pytest.mark.parametrize(
    "count,accepted", [(0, False), (1, False), (2, False), (3, True), (4, True)]
)
def test_final_recovery_requires_maximum_of_two_and_current_option_count(
    monkeypatch, count, accepted
):
    h = make_harness(monkeypatch)
    h.recovery.options = {str(i): "option" for i in range(count)}
    h.recovery.text = "<1>\n recovered \n<>"
    h.recovery.repaired_keys, h.recovery.mirror_repairs = ["A"], 7
    output = execute(h)
    assert output[0]["text"] == ("recovered" if accepted else "VL:A B C")
    recovery_logs = [args for args in h.records["info"] if "Phase 8" in args[0]]
    assert (
        recovery_logs
        == [
            (
                "VL_REBUILD page %d: Phase 8 recovered keys=%s mirror_repairs=%d",
                1,
                ["A"],
                7,
            )
        ]
        if accepted
        else recovery_logs == []
    )


def test_page_marker_cleanup_can_publish_an_empty_text_block(monkeypatch):
    h = make_harness(monkeypatch)
    h.cloud, h.result.fixed_text = True, "<1>"
    output = execute(h)
    assert len(output) == 1 and output[0]["text"] == output[0]["normalized_text"] == ""


def test_table_filter_uses_type_before_label_and_does_not_trim_type(monkeypatch):
    h = make_harness(monkeypatch)
    accepted = {"label": "TABLE_IMAGE", "nested": []}
    h.result.metadata = {
        "layout_blocks": [
            {"type": "text", "label": "table"},
            {"type": " table "},
            accepted,
            "table",
            {"type": "TABLE"},
        ]
    }
    output = execute(h)
    assert output[0]["vl_layout_blocks"] == [accepted, {"type": "TABLE"}]
    assert output[0]["vl_layout_blocks"][0] is accepted


def test_pp_logging_failure_retains_four_option_state_and_skips_vl(monkeypatch):
    h = make_harness(monkeypatch)
    h.options["PP:A B"] = dict.fromkeys("ABCD", "value")

    def fail_once(_):
        h.hooks.pop("info")
        raise RuntimeError("pp log")

    h.hooks["info"] = fail_once
    output = execute(h)
    assert output[0]["text"] == "PP:A B" and "fix" not in h.events
    assert "VL_REBUILD PP-OCRv4 failed page %d: %s" == h.records["warning"][0][0]


def test_later_page_vl_failure_discards_previously_built_blocks(monkeypatch):
    h = make_harness(monkeypatch)

    def fail_second(call):
        if call["context"]["page_num"] == 2:
            raise RuntimeError("second page")

    h.hooks["fix"] = fail_second
    assert execute(h, file_path="/synthetic/input.pdf") is None
    assert len(h.records["recover"]) == 1 and len(h.records["fix"]) == 2
    assert h.records["warning"][-1][0] == "VL_REBUILD failed: %s"


def test_recovery_failure_does_not_publish_partial_text(monkeypatch):
    h = make_harness(monkeypatch)
    error = RuntimeError("recovery")
    fail_at(h, "recover", error)
    assert execute(h) is None and h.records["warning"][-1] == (
        "VL_REBUILD failed: %s",
        error,
    )
