import pytest

from app.schemas.admin_questions import AdminQuestionAddOptionItem
from app.services.admin_question_service import (
    ensure_content_segments,
    merge_options,
    remove_option_image,
    remove_stem_image,
    upsert_option_image,
    upsert_stem_image,
)


def _item(text: str, key: str | None = None) -> AdminQuestionAddOptionItem:
    return AdminQuestionAddOptionItem(text=text, key=key)


# ── merge_options ───────────────────────────────────────────────────

def test_merge_options_auto_assigns_next_letter():
    merged = merge_options({"A": "1"}, [_item("2"), _item("3")])
    assert merged == {"A": "1", "B": "2", "C": "3"}


def test_merge_options_explicit_key_and_auto_skips_used():
    merged = merge_options({"A": "1", "B": "2"}, [_item("x", key="C"), _item("y")])
    assert merged == {"A": "1", "B": "2", "C": "x", "D": "y"}


def test_merge_options_duplicate_key_raises():
    with pytest.raises(ValueError):
        merge_options({"A": "1"}, [_item("dup", key="A")])


def test_merge_options_preserves_rich_existing_values():
    merged = merge_options({"A": {"text": "1", "segments": [{"type": "image", "url": "/x.png"}]}}, [_item("2")])
    assert merged["A"]["segments"][0]["url"] == "/x.png"


def test_merge_options_over_26_raises():
    existing = {chr(65 + i): str(i) for i in range(26)}
    with pytest.raises(ValueError):
        merge_options(existing, [_item("overflow")])


# ── ensure_content_segments ─────────────────────────────────────────

def test_ensure_content_segments_upgrades_legacy():
    out = ensure_content_segments({"text": "题干", "stem": "题干"})
    assert out["render_mode"] == "segments"
    assert out["segments"] == [{"type": "text", "text": "题干"}]
    assert out["text"] == "题干"


def test_ensure_content_segments_prefers_stem_over_text():
    # The miniprogram renders content.stem as the stem; the upgrade text
    # segment must match it, not content.text.
    out = ensure_content_segments({"text": "题干的 text", "stem": "题干 stem"})
    assert out["segments"] == [{"type": "text", "text": "题干 stem"}]


def test_ensure_content_segments_keeps_existing():
    content = {"text": "题干", "render_mode": "segments", "segments": [{"type": "image", "url": "/x.png"}]}
    assert ensure_content_segments(content) is content


# ── upsert_stem_image / remove_stem_image ───────────────────────────

def test_upsert_stem_image_appends_segment_and_upgrades():
    out = upsert_stem_image({"text": "题干"}, "http://x/s.png")
    assert out["segments"] == [
        {"type": "text", "text": "题干"},
        {"type": "image", "url": "http://x/s.png", "semantic_role": "content_image"},
    ]


def test_upsert_stem_image_replaces_existing():
    content = {"text": "题干", "render_mode": "segments", "segments": [
        {"type": "text", "text": "题干"},
        {"type": "image", "url": "http://x/old.png"},
    ]}
    out = upsert_stem_image(content, "http://x/new.png", replace_url="http://x/old.png")
    urls = [s["url"] for s in out["segments"] if s.get("type") == "image"]
    assert urls == ["http://x/new.png"]


def test_upsert_stem_image_replace_missing_raises():
    content = {"text": "题干", "render_mode": "segments", "segments": [{"type": "text", "text": "题干"}]}
    with pytest.raises(ValueError):
        upsert_stem_image(content, "http://x/new.png", replace_url="http://x/absent.png")


def test_remove_stem_image_drops_matching_segment():
    content = {"text": "题干", "render_mode": "segments", "segments": [
        {"type": "text", "text": "题干"},
        {"type": "image", "url": "http://x/s.png"},
    ]}
    out = remove_stem_image(content, "http://x/s.png")
    assert out["segments"] == [{"type": "text", "text": "题干"}]


def test_remove_stem_image_missing_raises():
    content = {"text": "题干", "render_mode": "segments", "segments": [{"type": "text", "text": "题干"}]}
    with pytest.raises(ValueError):
        remove_stem_image(content, "http://x/absent.png")


# ── upsert_option_image / remove_option_image ────────────────────────

def test_upsert_option_image_upgrades_flat_to_rich():
    out = upsert_option_image({"A": "1"}, "A", "http://x/o.png")
    assert out["A"] == {"text": "1", "segments": [{"type": "image", "url": "http://x/o.png", "semantic_role": "option_image"}]}


def test_upsert_option_image_preserves_existing_segments():
    out = upsert_option_image(
        {"A": {"text": "1", "segments": [{"type": "math_image", "url": "http://x/m.png"}]}},
        "A",
        "http://x/o.png",
    )
    assert [s["url"] for s in out["A"]["segments"]] == ["http://x/m.png", "http://x/o.png"]


def test_upsert_option_image_replaces_matching():
    out = upsert_option_image(
        {"A": {"text": "1", "segments": [{"type": "image", "url": "http://x/old.png"}]}},
        "A",
        "http://x/new.png",
        replace_url="http://x/old.png",
    )
    assert [s["url"] for s in out["A"]["segments"]] == ["http://x/new.png"]


def test_upsert_option_image_missing_key_raises():
    with pytest.raises(ValueError):
        upsert_option_image({"A": "1"}, "B", "http://x/o.png")


def test_upsert_option_image_empty_options_missing_key_raises():
    # Empty options must not silently create a phantom option A.
    with pytest.raises(ValueError):
        upsert_option_image({}, "A", "http://x/o.png")


def test_remove_option_image_degrades_to_flat():
    out = remove_option_image({"A": {"text": "1", "segments": [{"type": "image", "url": "http://x/o.png"}]}}, "A", "http://x/o.png")
    assert out == {"A": "1"}


def test_remove_option_image_keeps_other_segments():
    out = remove_option_image(
        {"A": {"text": "1", "segments": [{"type": "image", "url": "http://x/o.png"}, {"type": "math_image", "url": "http://x/m.png"}]}},
        "A",
        "http://x/o.png",
    )
    assert [s["url"] for s in out["A"]["segments"]] == ["http://x/m.png"]


def test_remove_option_image_missing_url_raises():
    with pytest.raises(ValueError):
        remove_option_image({"A": {"text": "1", "segments": [{"type": "image", "url": "http://x/o.png"}]}}, "A", "http://x/absent.png")
