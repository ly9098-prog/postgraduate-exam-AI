"""Partial assignments and per-page option merge state of VL rebuild."""

import pytest

from app.features import question_type_classifier
from tests.pipeline.vl_rebuild_support import execute, make_harness


@pytest.mark.parametrize("point", ["extract", "info"])
def test_pp_failure_after_text_preserves_partial_state(monkeypatch, point):
    h = make_harness(monkeypatch)
    original = {}
    error = RuntimeError(point)

    def extract(text):
        if text == "PP:A B":
            original.update(h.options.pop("PP:A B"))
            raise error
        return h.options.get(text, {})

    if point == "extract":
        monkeypatch.setattr(
            question_type_classifier, "extract_options_from_text", extract
        )
    else:

        def fail_once(_):
            h.hooks.pop("info")
            raise error

        h.hooks["info"] = fail_once
        h.results[b"image"] = None
    output = execute(h)
    assert output[0]["text"] == ("VL:A B C" if point == "extract" else "PP:A B")
    assert output[0]["vl_layout_blocks"] == (h.layout[:3] if point == "extract" else [])
    assert h.records["warning"][0][:2] == ("VL_REBUILD PP-OCRv4 failed page %d: %s", 1)
    assert h.records["warning"][0][2] is error
    assert ("PP:A B" not in h.options) == (point == "extract")
    assert "fix" in h.events


def test_pp_info_failure_after_four_options_skips_vl(monkeypatch):
    h = make_harness(monkeypatch)
    h.options["PP:A B"] = dict.fromkeys("ABCD", "value")
    error = RuntimeError("info")

    def fail_once(value):
        h.hooks.pop("info")
        raise error

    h.hooks["info"] = fail_once
    output = execute(h)
    assert output[0]["text"] == "PP:A B" and "fix" not in h.events
    assert h.records["warning"][0][2] is error


@pytest.mark.parametrize(
    "page,expected_width", [(0, 101), (1, 901), (2, 101), (3, 101)]
)
def test_pdf_page_dimension_uses_first_truthy_page_or_page_index_then_zero(
    monkeypatch, page, expected_width
):
    h = make_harness(monkeypatch)
    blocks = [
        {
            "page": page,
            "page_index": 2 if page == 0 else 0,
            "page_width": 901,
            "page_height": 1301,
        }
    ]
    output = execute(h, file_path="/synthetic/input.pdf", original_blocks=blocks)
    assert output[0]["page_width"] == expected_width


def test_first_page_dimension_wins_per_page(monkeypatch):
    h = make_harness(monkeypatch)
    blocks = [
        {"page": 1, "page_width": 701, "page_height": 1101},
        {"page": 1, "page_width": 901, "page_height": 1301},
    ]
    output = execute(h, file_path="/synthetic/input.pdf", original_blocks=blocks)
    assert output[0]["page_width"] == 701 and output[0]["page_height"] == 1101


def test_pdf_dimensions_fallback_to_pixmap_when_page_not_mapped(monkeypatch):
    h = make_harness(monkeypatch)
    blocks = [{"page": 9, "page_width": 999, "page_height": 999}]
    output = execute(h, file_path="/synthetic/input.pdf", original_blocks=blocks)
    assert output[0]["page_width"] == 101 and output[0]["page_height"] == 201


def test_original_line_match_stops_at_key_once_and_updates_count(monkeypatch):
    h = make_harness(monkeypatch)
    raw = "D. first D\nD. second D"
    h.options[raw] = {"A": "original A", "D": "original D"}
    h.options["VL:A B C"] = {"A": "vA"}
    h.options["PP:A B"] = {"A": "pA"}
    output = execute(h, original_raw_text=raw)
    assert output[0]["text"] == "PP:A B\nD. first D"
    assert h.options["PP:A B"] == {"A": "pA", "D": "original D"}
    assert [args[2] for args in h.records["info"] if "merged option" in args[0]] == [
        "D"
    ]


def test_original_option_mapping_and_best_text_are_not_reused_across_pages(monkeypatch):
    h = make_harness(monkeypatch)
    raw = "C. page one C\nD. page one D"
    h.options[raw] = {"C": "one C", "D": "one D"}
    h.options["VL:A B C"] = {"A": "vA"}
    h.options["PP:A B"] = {"A": "pA"}
    result = h.results[b"two"]
    result.fixed_text = "PP:A B"
    output = execute(h, file_path="/synthetic/input.pdf", original_raw_text=raw)
    assert output[0]["text"] == "PP:A B\nC. page one C\nD. page one D"
    assert output[1]["text"] == "PP:A B"
    assert (
        h.records["fix"][0]["context"]["page_num"]
        != h.records["fix"][1]["context"]["page_num"]
    )


def test_missing_option_mapping_remains_untouched(monkeypatch):
    h = make_harness(monkeypatch)
    raw = "D. original D"
    h.options[raw] = {"D": "original D"}
    h.options["VL:A B C"] = {}
    h.options["PP:A B"] = {}
    output = execute(h, original_raw_text=raw)
    assert output[0]["text"] == "VL:A B C\nD. original D"
    assert h.options.get("PP:A B") == {}
