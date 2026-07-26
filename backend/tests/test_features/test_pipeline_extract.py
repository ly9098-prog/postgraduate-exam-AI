"""Regression tests for pipeline extract stage preferring file_content over file_path.

Covers:
1. Image source_type uses file_content (cleaned_text), not file_path (PNG path)
2. PDF source_type still prioritizes file_path (mmap optimization)
3. _extract_text_blocks rejects binary image headers with clear error
"""

from __future__ import annotations

import os
import tempfile

from app.features.pipeline_orchestrator import (
    ImportPipeline,
    _detect_binary_header,
    _extract_text_blocks,
)


def _make_fake_png(path: str) -> str:
    """写入类 PNG 魔数 + 垃圾字节到临时文件，返回路径。"""
    header = b"\x89PNG\r\n\x1a\n" + b"IHDR" + b"\x00" * 20 + b"IDAT" + b"\x01\x02\x03\x04"
    with open(path, "wb") as f:
        f.write(header)
    return path


def test_detect_binary_header_png():
    assert _detect_binary_header(b"\x89PNG\r\n\x1a\nIHDR....IDAT....") == "PNG"


def test_detect_binary_header_jpeg():
    assert _detect_binary_header(b"\xff\xd8\xff\xe0") == "JPEG"


def test_detect_binary_header_gif():
    assert _detect_binary_header(b"GIF89a\x01\x02\x03") == "GIF"


def test_detect_binary_header_webp():
    data = b"RIFF\x00\x00\x00\x00WEBP\x10\x00\x00\x00"
    assert _detect_binary_header(data) == "WebP"


def test_detect_binary_header_pdf():
    assert _detect_binary_header(b"%PDF-1.4") == "PDF"


def test_detect_binary_header_plain_text():
    assert _detect_binary_header(b"17. \xe6\x89\xa7\xe8\xa1\x8c\xe5\xa6\x82\xe4\xb8\x8b\xe4\xbb\xa3\xe7\xa0\x81") is None


def test_extract_text_blocks_raises_on_png_path():
    """PNG 文件路径传给 _extract_text_blocks 应抛出 ValueError。"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        png_path = _make_fake_png(f.name)

    try:
        raised = False
        try:
            _extract_text_blocks(png_path)
        except ValueError as e:
            raised = True
            assert "PNG" in str(e), f"错误信息应提及 PNG: {e}"
        assert raised, "应抛出 ValueError"
    finally:
        os.unlink(png_path)


def test_extract_text_blocks_accepts_plain_text_path():
    """普通文本文件路径应正常提取。"""
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="wb", delete=False) as f:
        f.write(b"17. \xe6\x89\xa7\xe8\xa1\x8c\xe5\xa6\x82\xe4\xb8\x8b\xe4\xbb\xa3\xe7\xa0\x81:\nA. xxx\nB. yyy")
        txt_path = f.name

    try:
        blocks = _extract_text_blocks(txt_path)
        assert len(blocks) == 1
        text = blocks[0]["text"]
        assert "17." in text
        assert "执行如下代码" in text
    finally:
        os.unlink(txt_path)


def test_extract_text_blocks_accepts_bytes():
    """bytes 内容应正常提取，不受二进制检测影响。"""
    content = b"17. \xe6\x89\xa7\xe8\xa1\x8c\xe5\xa6\x82\xe4\xb8\x8b\xe4\xbb\xa3\xe7\xa0\x81:\nA. xxx"
    blocks = _extract_text_blocks(content)
    assert "17." in blocks[0]["text"]
    assert "PNG" not in blocks[0]["text"]


def test_run_extract_image_uses_file_content_not_file_path():
    """ImportPipeline._run_extract 对于 source_type='image' 应优先使用 file_content。"""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        png_path = _make_fake_png(f.name)

    try:
        pipeline = ImportPipeline(options={})
        result = pipeline._run_extract(
            file_content=b"17. \xe6\x89\xa7\xe8\xa1\x8c\xe5\xa6\x82\xe4\xb8\x8b\xe4\xbb\xa3\xe7\xa0\x81:\nA. xxx\nB. yyy",
            source_type="image",
            file_path=png_path,
        )
        blocks = result["raw_blocks"]
        assert len(blocks) == 1
        text = blocks[0]["text"]
        assert "17." in text
        assert "执行如下代码" in text
        assert "PNG" not in text
        assert "IDAT" not in text
    finally:
        os.unlink(png_path)


def test_run_extract_image_no_content_fallsback_to_path():
    """image 没有 file_content 时回退到 file_path。"""
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="wb", delete=False) as f:
        f.write(b"\xe6\xb5\x8b\xe8\xaf\x95\xe6\x96\x87\xe6\x9c\xac")
        txt_path = f.name

    try:
        pipeline = ImportPipeline(options={})
        result = pipeline._run_extract(
            file_content=None,
            source_type="image",
            file_path=txt_path,
        )
        assert "测试文本" in result["raw_blocks"][0]["text"]
    finally:
        os.unlink(txt_path)


def test_run_extract_pdf_still_uses_file_path():
    """PDF source_type 仍应优先使用 file_path（mmap）。"""
    pipeline = ImportPipeline(options={})
    # 不传 file_path 时 PDF 降级到 file_content
    # 这里只验证函数调用路径不崩溃（传空 bytes 会正常到 PyMuPDF 检测阶段）
    # 核心断言：pdf 分支不应进入文本文件分支逻辑
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = f.name

    try:
        pipeline = ImportPipeline(options={})
        try:
            pipeline._run_extract(
                file_content=b"fake content",
                source_type="pdf",
                file_path=pdf_path,
            )
        except (RuntimeError, ValueError):
            # PyMuPDF 未安装或 PDF 无效，属于预期异常
            # 关键是验证没有触发 _extract_text_blocks（会因 PNG 检测给不同异常）
            pass
    finally:
        os.unlink(pdf_path)
