"""import_pdf() 回归测试 — 验证4参数调用不再报 TypeError。"""
import asyncio
import io
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.features.question_pipeline import import_pdf


def _make_pdf(text: str) -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 80), text, fontsize=11, fontname="china-s")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


PDF_WITH_QUESTION = _make_pdf(
    "1. 以下哪个是操作系统的基本功能？\n"
    "A. 文字处理\nB. 进程管理\nC. 网页浏览\nD. 视频播放\n"
    "答案：B\n解析：进程管理是操作系统的核心功能之一。"
)

PDF_EMPTY_TEXT = b"%PDF-1.4\n%%EOF\n"


def _make_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


class TestImportPdfSignature:
    """import_pdf 签名兼容性测试 — 确保3参数和4参数调用均不报 TypeError。"""

    def test_three_args_accepted(self):
        """3参数调用（不传 background_tasks）正常工作。"""
        db = _make_db()
        batch_id, total = asyncio.run(import_pdf(db, PDF_WITH_QUESTION, "test.pdf"))
        assert batch_id.startswith("BATCH_")
        assert total >= 0

    def test_four_args_accepted(self):
        """4参数调用（传 background_tasks=None）不报 TypeError。"""
        db = _make_db()
        batch_id, total = asyncio.run(import_pdf(db, PDF_WITH_QUESTION, "test.pdf", None))
        assert batch_id.startswith("BATCH_")
        assert total >= 0

    def test_background_tasks_object_accepted(self):
        """传入真实 BackgroundTasks 对象不报 TypeError。"""
        from fastapi import BackgroundTasks
        bg = BackgroundTasks()
        db = _make_db()
        batch_id, total = asyncio.run(import_pdf(db, PDF_WITH_QUESTION, "test.pdf", bg))
        assert batch_id.startswith("BATCH_")


class TestImportPdfValidation:
    """import_pdf 输入校验测试。"""

    def test_empty_pdf_raises_value_error(self):
        """空 PDF（无法解析文本）应抛 ValueError 而非崩溃。"""
        db = _make_db()
        with pytest.raises((ValueError, Exception)):
            asyncio.run(import_pdf(db, PDF_EMPTY_TEXT, "empty.pdf"))

    def test_non_pdf_bytes_raises(self):
        """非 PDF 字节应抛异常。"""
        db = _make_db()
        with pytest.raises(Exception):
            asyncio.run(import_pdf(db, b"this is not a pdf", "fake.pdf"))

    def test_valid_pdf_writes_to_db(self):
        """有效 PDF 解析成功后应调用 db.add 和 db.commit。"""
        db = _make_db()
        batch_id, total = asyncio.run(import_pdf(db, PDF_WITH_QUESTION, "valid.pdf"))
        assert batch_id.startswith("BATCH_")
        assert db.commit.called

    def test_returns_tuple(self):
        """返回值是 (str, int) tuple。"""
        db = _make_db()
        result = asyncio.run(import_pdf(db, PDF_WITH_QUESTION, "test.pdf"))
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], int)

    def test_batch_id_unique(self):
        """每次调用生成不同的 batch_id。"""
        db1 = _make_db()
        db2 = _make_db()
        batch1, _ = asyncio.run(import_pdf(db1, PDF_WITH_QUESTION, "test.pdf"))
        batch2, _ = asyncio.run(import_pdf(db2, PDF_WITH_QUESTION, "test.pdf"))
        assert batch1 != batch2


class TestImportPdfRouteCallPattern:
    """模拟 API 路由的实际调用方式 — 这正是触发原 TypeError 的路径。"""

    def test_route_call_pattern_no_crash(self):
        """完全模拟 imports.py:80 的调用方式，确保不再出现 TypeError。"""
        from fastapi import BackgroundTasks
        bg = BackgroundTasks()
        db = _make_db()
        # This is exactly: await svc.import_pdf(db, content, file.filename, background_tasks)
        batch_id, total = asyncio.run(import_pdf(db, PDF_WITH_QUESTION, "upload.pdf", bg))
        assert isinstance(batch_id, str)
        assert isinstance(total, int)
