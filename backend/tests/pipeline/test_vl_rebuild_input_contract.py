"""Source/configuration/session boundaries of VL rebuild, before extraction."""

import asyncio
from copy import deepcopy

import pytest

from tests.pipeline.vl_rebuild_support import execute, fail_at, make_harness


def test_image_configuration_and_call_order(monkeypatch):
    h = make_harness(monkeypatch)
    execute(h)
    assert (
        h.events
        == """
        construct_router configure isfile file_open file_enter file_read file_exit profile
        pp detect extract info fix run repair detect extract info recover extract info
    """.split()
    )
    assert h.records["configure"] == [
        {
            "ocr_fix_strategy": "manual-contract",
            "ocr_fix_model": "paddleocr-vl",
            "paddleocr_vl_api_token": "synthetic-token",
            "paddleocr_vl_base_url": "synthetic-base",
            "paddleocr_vl_model": "synthetic-model",
        }
    ]
    assert h.records["file_open"] == [("/synthetic/input.png", "rb")]
    assert h.records["fix"] == [
        {
            "image": b"image",
            "ocr_text": "",
            "context": {
                "page_num": 1,
                "filename": "page_1.png",
                "entry_point": "vl_rebuild",
            },
        }
    ]
    assert h.records["run"][0] is h.records["fix"][0]
    assert h.records["info"][-1] == ("VL_REBUILD: %d blocks from %s", 1, "image")


def test_image_complete_shape_keeps_originals_and_layout_references(monkeypatch):
    h = make_harness(monkeypatch)
    layout_before, blocks_before = (
        deepcopy(h.layout),
        deepcopy(h.arguments["original_blocks"]),
    )
    output = execute(h)
    assert output == [
        {
            "page": 1,
            "page_index": 1,
            "block_index": 0,
            "text": "VL:A B C",
            "normalized_text": "VL:A B C",
            "boxes": [],
            "page_width": 801,
            "page_height": 1201,
            "source": "vl_rebuild",
            "has_boxes": False,
            "vl_layout_blocks": layout_before[:3],
        }
    ]
    assert output[0]["text"] is output[0]["normalized_text"]
    assert all(output[0]["vl_layout_blocks"][i] is h.layout[i] for i in range(3))
    assert h.layout == layout_before and h.arguments["original_blocks"] == blocks_before


@pytest.mark.parametrize(
    "config,path,message",
    [
        (None, "bad.webp", "VL_REBUILD: no vision config available"),
        ({}, "bad.webp", "VL_REBUILD: no vision config available"),
        ({"api_key": "x"}, "bad.webp", "VL_REBUILD: unsupported file type: %s"),
        ({"api_key": "x"}, "bad.txt", "VL_REBUILD: unsupported file type: %s"),
    ],
)
def test_input_rejection_precedes_router_and_source_ports(
    monkeypatch, config, path, message
):
    h = make_harness(monkeypatch)
    assert execute(h, vl_config=config, file_path=path) is None
    assert h.events == ["warning"] and h.records["warning"][0][0] == message


@pytest.mark.parametrize(
    "point",
    [
        "file_open",
        "file_enter",
        "file_read",
        "file_exit",
        "configure",
        "construct_router",
    ],
)
def test_ordinary_source_and_router_failures_return_none(monkeypatch, point):
    h = make_harness(monkeypatch)
    error = RuntimeError(point)
    fail_at(h, point, error)
    assert execute(h) is None
    assert h.records["warning"][-1] == ("VL_REBUILD failed: %s", error)
    assert "profile" not in h.events and "fix" not in h.events


def test_missing_token_is_rejected_inside_outer_fallback(monkeypatch):
    h = make_harness(monkeypatch)
    assert execute(h, vl_config={"model_name": "model"}) is None
    assert h.events == ["warning"] and h.records["warning"] == [
        ("VL_REBUILD: PaddleOCR-VL not configured",)
    ]


def test_legacy_token_and_empty_url_model_use_original_defaults(monkeypatch):
    h = make_harness(monkeypatch)
    execute(
        h,
        vl_config={
            "paddleocr_vl_api_token": "legacy",
            "api_base_url": "",
            "model_name": None,
        },
    )
    assert h.records["configure"][0] == {
        "ocr_fix_strategy": "manual-contract",
        "ocr_fix_model": "paddleocr-vl",
        "paddleocr_vl_api_token": "legacy",
        "paddleocr_vl_base_url": "https://paddleocr.aistudio-app.com",
        "paddleocr_vl_model": "PaddleOCR-VL-1.6",
    }


def test_missing_image_stops_after_router_configuration(monkeypatch):
    h = make_harness(monkeypatch)
    h.exists = False
    assert execute(h) is None
    assert h.events == ["construct_router", "configure", "isfile", "warning"]


@pytest.mark.parametrize("blocks", [[], [{"page_width": 0, "page_height": None}]])
def test_image_dimensions_fall_back_to_original_defaults(monkeypatch, blocks):
    h = make_harness(monkeypatch)
    output = execute(h, original_blocks=blocks)
    assert (output[0]["page_width"], output[0]["page_height"]) == (800, 1200)


def test_pdf_all_pages_render_and_close_before_any_ocr(monkeypatch):
    h = make_harness(monkeypatch)
    blocks = [
        {"page": 0, "page_index": 1, "page_width": 901, "page_height": 1301},
        {"page": 1, "page_width": 999, "page_height": 999},
    ]
    output = execute(h, file_path="/synthetic/input.PDF", original_blocks=blocks)
    assert h.records["open_pdf"] == [("/synthetic/input.PDF", {"filetype": "pdf"})]
    assert h.records["pixmap"] == [(1, {"dpi": 150}), (2, {"dpi": 150})]
    assert h.records["png"] == [(1, "png"), (2, "png")]
    assert h.records["pp"] == [b"one", b"two"]
    assert h.records["fix"] == [
        {
            "image": image,
            "ocr_text": "",
            "context": {
                "page_num": page,
                "filename": f"page_{page}.png",
                "entry_point": "vl_rebuild",
            },
        }
        for page, image in enumerate((b"one", b"two"), 1)
    ]
    assert (
        h.events.index("close_pdf") < h.events.index("profile") < h.events.index("pp")
    )
    assert [
        (
            b["page"],
            b["page_index"],
            b["block_index"],
            b["page_width"],
            b["page_height"],
        )
        for b in output
    ] == [(1, 1, 0, 901, 1301), (2, 2, 1, 102, 202)]
    assert h.records["info"][-1] == ("VL_REBUILD: %d blocks from %s", 2, "PDF")


@pytest.mark.parametrize("point", ["page_count", "page", "pixmap", "png"])
@pytest.mark.parametrize("kind", [RuntimeError, asyncio.CancelledError])
def test_pdf_close_runs_on_render_error_or_cancellation(monkeypatch, point, kind):
    h = make_harness(monkeypatch)
    error = kind(point)
    fail_at(h, point, error)
    if kind is RuntimeError:
        assert execute(h, file_path="/synthetic/input.pdf") is None
        assert h.records["warning"][-1] == ("VL_REBUILD failed: %s", error)
    else:
        with pytest.raises(kind) as caught:
            execute(h, file_path="/synthetic/input.pdf")
        assert caught.value is error
    assert h.events.count("close_pdf") == 1 and "profile" not in h.events


def test_pdf_without_pages_closes_then_returns_no_blocks(monkeypatch):
    h = make_harness(monkeypatch)
    h.pngs = []
    assert execute(h, file_path="/synthetic/empty.pdf") is None
    assert h.events[-3:] == ["close_pdf", "profile", "warning"]
    assert h.records["warning"][-1] == ("VL_REBUILD: no blocks produced",)


def test_suppressed_image_read_error_preserves_original_unbound_failure(monkeypatch):
    h = make_harness(monkeypatch)
    h.suppress_file = True
    error = RuntimeError("read")
    fail_at(h, "file_read", error)
    assert execute(h) is None
    assert h.records["file_exit"] == [(RuntimeError, error)]
    warning = h.records["warning"][-1]
    assert warning[0] == "VL_REBUILD failed: %s" and isinstance(
        warning[1], UnboundLocalError
    )
    assert "image_bytes" in str(warning[1]) and "profile" not in h.events
