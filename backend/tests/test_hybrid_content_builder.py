"""HybridContentBuilder 单元测试"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.hybrid_content_builder import build
from app.services.math_region_detector import MathRegion, MathRegionType


def _region(raw_latex, url, rtype=MathRegionType.INLINE, page=0):
    return MathRegion(
        page_num=page,
        bbox=(10.0, 10.0, 100.0, 30.0),
        region_type=rtype,
        raw_latex=raw_latex,
        image_url=url,
    )


# ── 无 region 时退化为纯文本 ──────────────────────────────────────────────────

def test_build_no_regions_returns_plain_text():
    result = build("hello world", [])
    assert result == {"text": "hello world"}
    assert "segments" not in result
    assert "render_mode" not in result


def test_build_no_valid_url_returns_plain_text():
    r = MathRegion(0, (0, 0, 10, 10), MathRegionType.INLINE, "x^2", None)
    result = build("some text", [r])
    assert result == {"text": "some text"}


# ── 有 region 时产生 segments ─────────────────────────────────────────────────

def test_build_with_regions_has_segments():
    r = _region("\\int_0^1 x dx", "http://localhost/f.png")
    result = build("求\\int_0^1 x dx的值", [r])
    assert result["render_mode"] == "segments"
    assert "segments" in result
    assert len(result["segments"]) > 0


def test_build_segment_types():
    r = _region("\\alpha", "http://localhost/a.png")
    result = build("已知\\alpha>0", [r])
    types = [s["type"] for s in result["segments"]]
    assert "math_image" in types
    assert "text" in types


def test_build_math_image_fields():
    r = _region("\\beta", "http://localhost/b.png", MathRegionType.DISPLAY)
    result = build("\\beta的值", [r])
    math_segs = [s for s in result["segments"] if s["type"] == "math_image"]
    assert len(math_segs) == 1
    seg = math_segs[0]
    assert seg["url"] == "http://localhost/b.png"
    assert seg["alt"] == "\\beta"
    assert seg["display"] is True


def test_build_inline_display_false():
    r = _region("x^2", "http://localhost/x.png", MathRegionType.INLINE)
    result = build("f(x)=x^2", [r])
    math_segs = [s for s in result["segments"] if s["type"] == "math_image"]
    assert math_segs[0]["display"] is False


def test_build_mixed_type_display_false():
    r = _region("f(x)", "http://localhost/f.png", MathRegionType.MIXED)
    result = build("f(x)是连续函数", [r])
    math_segs = [s for s in result["segments"] if s["type"] == "math_image"]
    assert math_segs[0]["display"] is False


# ── content.text 重建规则 ─────────────────────────────────────────────────────

def test_build_text_uses_alt_placeholder():
    r = _region("\\int_0^1", "http://localhost/i.png")
    result = build("求\\int_0^1 dx", [r])
    assert "$\\int_0^1$" in result["text"]


def test_build_text_no_math_escape_when_no_regions():
    result = build("纯文本，无公式", [])
    assert result["text"] == "纯文本，无公式"


# ── 多个 region ───────────────────────────────────────────────────────────────

def test_build_multiple_regions():
    r1 = _region("\\alpha", "http://localhost/a.png")
    r2 = _region("\\beta", "http://localhost/b.png")
    result = build("\\alpha加\\beta", [r1, r2])
    math_segs = [s for s in result["segments"] if s["type"] == "math_image"]
    assert len(math_segs) == 2
    urls = {s["url"] for s in math_segs}
    assert "http://localhost/a.png" in urls
    assert "http://localhost/b.png" in urls


def test_build_region_not_in_text_appended():
    """raw_latex 在 text 中找不到时，segment 仍被追加（不丢失）。"""
    r = _region("\\gamma", "http://localhost/g.png")
    result = build("完全不含该公式的文本", [r])
    math_segs = [s for s in result["segments"] if s["type"] == "math_image"]
    assert len(math_segs) == 1


def test_build_text_reconstruction_complete():
    """text 字段包含原始非公式内容。"""
    r = _region("x^2", "http://localhost/x.png")
    result = build("设f(x)=x^2，求导", [r])
    # text 应包含前后文字和公式占位
    assert "设f(x)=" in result["text"]
    assert "，求导" in result["text"]
    assert "$x^2$" in result["text"]
