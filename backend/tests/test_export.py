"""Tests for the wrong-questions export feature.

Covers: range resolution, sorting, grouping, snapshots, PDF generation,
task lifecycle, idempotency, error handling, and edge cases.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.features.question_type import (
    QT_FILL_BLANK,
    QT_MULTIPLE_CHOICE,
    QT_SINGLE_CHOICE,
    QT_SUBJECTIVE,
    QT_TRUE_FALSE,
)
from app.schemas.export_task import (
    ExportAnswerPosition,
    ExportRangeType,
    ExportSortBy,
    ExportTaskStatus,
)
from app.services.export.cleanup import cleanup_expired
from app.services.export.latex_render import find_latex_segments, has_latex
from app.services.export.range_resolver import resolve_range
from app.services.export.service import (
    _build_filename,
    _build_title,
    _sanitize_filename,
)
from app.services.export.snapshot_service import create_snapshot
from app.services.export.sorter import sort_questions
from app.services.export.space_allocator import get_answer_space_mm

# ═══════════════════════════════════════════════════
# Filename helpers
# ═══════════════════════════════════════════════════


class TestSanitizeFilename:
    def test_removes_invalid_chars(self):
        result = _sanitize_filename('bad/name:file*')
        assert '/' not in result
        assert ':' not in result
        assert '*' not in result

    def test_trims_spaces_and_dots(self):
        result = _sanitize_filename('  my title.  ')
        assert result == 'my title'

    def test_fallback_on_empty(self):
        result = _sanitize_filename('')
        assert result == '错题巩固练习'

    def test_limits_length(self):
        long_name = 'a' * 500
        result = _sanitize_filename(long_name)
        assert len(result.encode('utf-8')) <= 200


class TestBuildFilename:
    def test_normal_case(self):
        result = _build_filename('数学错题巩固练习', '20260725', 'pdf')
        assert result.startswith('数学错题巩固练习_20260725')
        assert result.endswith('.pdf')

    def test_invalid_chars_cleaned(self):
        result = _build_filename('bad/file:name', '20260725', 'pdf')
        assert '/' not in result
        assert ':' not in result
        assert result.endswith('.pdf')


# ═══════════════════════════════════════════════════
# Title builder
# ═══════════════════════════════════════════════════


class TestBuildTitle:
    def test_single_subject(self):
        assert _build_title([{"label": "数学"}]) == "数学错题巩固练习"

    def test_two_subjects(self):
        assert _build_title([{"label": "数学"}, {"label": "英语"}]) == "数学、英语错题巩固练习"

    def test_three_subjects(self):
        result = _build_title([{"label": "数学"}, {"label": "英语"}, {"label": "政治"}])
        assert result == "数学、英语、政治错题巩固练习"

    def test_more_than_three(self):
        result = _build_title([{"label": "数学"}, {"label": "英语"}, {"label": "政治"}, {"label": "专业课"}])
        assert result == "数学、英语、政治等错题巩固练习"

    def test_empty(self):
        assert _build_title([]) == "错题巩固练习"

    def test_no_labels(self):
        assert _build_title([{}, {}]) == "错题巩固练习"


# ═══════════════════════════════════════════════════
# Space allocator
# ═══════════════════════════════════════════════════


class TestSpaceAllocator:
    def test_choice_zero_space(self):
        assert get_answer_space_mm("standard", QT_SINGLE_CHOICE) == 0
        assert get_answer_space_mm("compact", QT_MULTIPLE_CHOICE) == 0

    def test_true_false_zero_space(self):
        assert get_answer_space_mm("standard", QT_TRUE_FALSE) == 0

    def test_fill_blank_has_space(self):
        assert get_answer_space_mm("standard", QT_FILL_BLANK) > 0

    def test_subjective_has_large_space(self):
        assert get_answer_space_mm("spacious", QT_SUBJECTIVE) > 0

    def test_space_style_increases(self):
        compact = get_answer_space_mm("compact", QT_SUBJECTIVE)
        standard = get_answer_space_mm("standard", QT_SUBJECTIVE)
        spacious = get_answer_space_mm("spacious", QT_SUBJECTIVE)
        assert compact < standard < spacious

    def test_unknown_type_defaults_to_subjective(self):
        assert get_answer_space_mm("standard", "unknown_type") > 0


# ═══════════════════════════════════════════════════
# LaTeX rendering
# ═══════════════════════════════════════════════════


class TestLatexFindSegments:
    def test_plain_text_no_latex(self):
        result = find_latex_segments("这是纯文本")
        assert len(result) == 1
        assert result[0]["type"] == "text"

    def test_inline_latex(self):
        result = find_latex_segments("公式 $E=mc^2$ 结束")
        assert len(result) == 3
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "latex"
        assert result[1]["content"] == "E=mc^2"

    def test_has_latex(self):
        assert has_latex("公式 $x^2$ 测试")
        assert not has_latex("纯文本")


# ═══════════════════════════════════════════════════
# Range resolver (unit tests with mocks)
# ═══════════════════════════════════════════════════


@pytest.fixture
def mock_db():
    db = MagicMock()
    result = MagicMock()
    async def async_execute(*args, **kwargs):
        return result
    db.execute = async_execute
    db._result = result
    return db


class TestRangeResolver:
    @pytest.mark.asyncio
    async def test_all_range(self, mock_db):
        mock_db._result.fetchall.return_value = [(1,), (2,), (3,)]
        result = await resolve_range(mock_db, 1, ExportRangeType.ALL)
        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_all_range_ignores_filters(self, mock_db):
        mock_db._result.fetchall.return_value = [(1,), (2,)]
        result = await resolve_range(
            mock_db, 1, ExportRangeType.ALL,
            filters={"subject": "math", "error_type": "careless"},
        )
        assert result == [1, 2]

    @pytest.mark.asyncio
    async def test_selected_ownership_validation(self, mock_db):
        mock_db._result.fetchall.return_value = [(1,), (3,)]
        # Any invalid ID raises ValueError (opaque error)
        with pytest.raises(ValueError, match="部分题目无法导出"):
            await resolve_range(
                mock_db, 1, ExportRangeType.SELECTED,
                selected_ids=[1, 2, 3, 4],
            )

    @pytest.mark.asyncio
    async def test_selected_all_valid_passes(self, mock_db):
        mock_db._result.fetchall.return_value = [(1,), (2,), (3,)]
        result = await resolve_range(
            mock_db, 1, ExportRangeType.SELECTED,
            selected_ids=[1, 2, 3],
        )
        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_selected_empty_list_raises(self, mock_db):
        with pytest.raises(ValueError, match="为空"):
            await resolve_range(mock_db, 1, ExportRangeType.SELECTED, selected_ids=[])

    @pytest.mark.asyncio
    async def test_all_over_100_passes_preview(self, mock_db):
        """Range resolver no longer enforces the 100-limit — that's checked at create time."""
        mock_db._result.fetchall.return_value = [(i,) for i in range(101)]
        result = await resolve_range(mock_db, 1, ExportRangeType.ALL)
        assert len(result) == 101


# ═══════════════════════════════════════════════════
# Sorting
# ═══════════════════════════════════════════════════


class TestSorter:
    @pytest.mark.asyncio
    async def test_empty_list(self, mock_db):
        result = await sort_questions(mock_db, 1, [], ExportSortBy.NEWEST)
        assert result == []

    @pytest.mark.asyncio
    async def test_random_is_deterministic(self, mock_db):
        ids = list(range(10))
        r1 = await sort_questions(mock_db, 1, ids, ExportSortBy.RANDOM)
        assert len(r1) == len(ids)
        assert set(r1) == set(ids)


# ═══════════════════════════════════════════════════
# Snapshots
# ═══════════════════════════════════════════════════


class TestSnapshotService:
    @pytest.mark.asyncio
    async def test_create_and_load_snapshot(self, mock_db):
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        sid = await create_snapshot(mock_db, 1, {"questions": [], "config": {}})
        assert sid is not None

    @pytest.mark.asyncio
    async def test_snapshot_over_limit_raises(self, mock_db):
        with pytest.raises(ValueError, match="超出限制"):
            await create_snapshot(mock_db, 1, {"data": "x" * (6 * 1024 * 1024)})


# ═══════════════════════════════════════════════════
# Task state machine validation
# ═══════════════════════════════════════════════════


class TestTaskStatus:
    def test_status_enum_values(self):
        assert ExportTaskStatus.PENDING == "pending"
        assert ExportTaskStatus.PROCESSING == "processing"
        assert ExportTaskStatus.COMPLETED == "completed"
        assert ExportTaskStatus.FAILED == "failed"
        assert ExportTaskStatus.EXPIRED == "expired"

    def test_export_sort_by_complete(self):
        assert ExportSortBy.NEWEST == "newest"
        assert ExportSortBy.OLDEST == "oldest"
        assert ExportSortBy.ORIGINAL == "original"
        assert ExportSortBy.RANDOM == "random"
        assert ExportSortBy.KNOWLEDGE_POINT == "knowledge_point"
        assert ExportSortBy.QUESTION_TYPE == "question_type"

    def test_answer_position_enum(self):
        assert ExportAnswerPosition.NONE == "none"
        assert ExportAnswerPosition.AFTER_QUESTION == "after_question"
        assert ExportAnswerPosition.AT_END == "at_end"


# ═══════════════════════════════════════════════════
# PDF generation smoke test
# ═══════════════════════════════════════════════════


class TestPdfGeneration:
    def test_generate_minimal_pdf(self):
        from fpdf import FPDF
        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.add_font("WenQuanYi", "", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")
        pdf.add_page()
        pdf.set_font("WenQuanYi", "", 12)
        pdf.multi_cell(170, 6, text="测试错题导出试卷")
        pdf.set_font("WenQuanYi", "", 10)
        pdf.multi_cell(170, 5, text="1. [单选题] 这是一道测试题")
        pdf.multi_cell(170, 5, text="A. 选项一")
        data = pdf.output()
        assert len(data) > 100
        assert data[:4] == b"%PDF"

    def test_blank_question_returns_empty_text(self):
        from app.services.export.pdf_exporter import PdfExporter
        exporter = PdfExporter()
        result = exporter._get_question_text({"content": {}})
        assert result == ""


# ═══════════════════════════════════════════════════
# Cleanup tests
# ═══════════════════════════════════════════════════


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_expired_no_tasks(self, mock_db):
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_db._result.scalars.return_value = mock_scalars
        result = await cleanup_expired(mock_db)
        assert result["tasks_expired"] == 0

    @pytest.mark.asyncio
    async def test_filename_sanitization_unicode(self):
        result = _sanitize_filename("数学/物理:化学*测试?")
        assert "/" not in result
        assert result


# ═══════════════════════════════════════════════════
# Capability service tests
# ═══════════════════════════════════════════════════


class TestCapabilityService:
    def test_parse_allowed_ids_empty(self):
        from app.services.export.capability import _parse_allowed_ids
        assert _parse_allowed_ids("") == set()
        assert _parse_allowed_ids("  ") == set()
        assert _parse_allowed_ids(None) == set()

    def test_parse_allowed_ids_normal(self):
        from app.services.export.capability import _parse_allowed_ids
        assert _parse_allowed_ids("1,2,3") == {1, 2, 3}

    def test_parse_allowed_ids_with_spaces(self):
        from app.services.export.capability import _parse_allowed_ids
        assert _parse_allowed_ids(" 1 , 2 , 3 ") == {1, 2, 3}

    def test_parse_allowed_ids_invalid_skipped(self):
        from app.services.export.capability import _parse_allowed_ids
        assert _parse_allowed_ids("1,,abc,2") == {1, 2}

    def test_parse_allowed_ids_duplicates(self):
        from app.services.export.capability import _parse_allowed_ids
        assert _parse_allowed_ids("1,2,2,3,1") == {1, 2, 3}

    def test_ensure_format_allowed_pdf_always(self):
        from app.services.export.capability import ensure_format_allowed
        # pdf should never raise
        ensure_format_allowed("pdf")

    def test_validate_export_range_zero_raises(self):
        from fastapi import HTTPException

        from app.services.export.capability import validate_export_range
        with pytest.raises(HTTPException) as exc:
            validate_export_range("all", None, 0)
        assert exc.value.status_code == 400
        assert "no_questions" in str(exc.value.detail)

    def test_validate_export_range_exceeds_max(self):
        from fastapi import HTTPException

        from app.services.export.capability import validate_export_range
        with pytest.raises(HTTPException) as exc:
            validate_export_range("all", None, 999)
        assert exc.value.status_code == 400
        assert "too_many_questions" in str(exc.value.detail)


# ═══════════════════════════════════════════════════
# Storage backend contract tests
# ═══════════════════════════════════════════════════


class TestLocalFileStorage:
    @pytest.mark.asyncio
    async def test_upload_and_delete(self, tmp_path, monkeypatch):
        """Upload a file, verify it exists, delete it, verify it's gone."""
        from app.services.storage_backend import LocalFileStorage
        prefix = str(tmp_path / "exports")
        storage = LocalFileStorage(prefix=prefix)
        data = b"test pdf content"
        url = await storage.upload("test/1/test.pdf", data)
        assert url is not None

        # Verify file exists on disk
        file_path = tmp_path / "exports" / "test" / "1" / "test.pdf"
        assert file_path.exists()
        assert file_path.read_bytes() == data

        # Delete using the key (relative path, not full filesystem path)
        deleted = await storage.delete("test/1/test.pdf")
        assert deleted is True
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_true(self, tmp_path):
        """Deleting a file that doesn't exist should return True (idempotent)."""
        from app.services.storage_backend import LocalFileStorage
        storage = LocalFileStorage(prefix=str(tmp_path))
        deleted = await storage.delete("nonexistent/file.pdf")
        assert deleted is True

    @pytest.mark.asyncio
    async def test_exists_after_upload(self, tmp_path):
        from app.services.storage_backend import LocalFileStorage
        storage = LocalFileStorage(prefix=str(tmp_path))
        await storage.upload("exists/test.pdf", b"data")
        exists = await storage.exists("exists/test.pdf")
        assert exists is True

    @pytest.mark.asyncio
    async def test_exists_nonexistent(self, tmp_path):
        from app.services.storage_backend import LocalFileStorage
        storage = LocalFileStorage(prefix=str(tmp_path))
        exists = await storage.exists("ghost/file.pdf")
        assert exists is False

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self):
        from app.services.storage_backend import LocalFileStorage
        storage = LocalFileStorage(prefix="/safe/prefix")
        # Path traversal with ".." should be rejected
        deleted = await storage.delete("../../etc/passwd")
        assert deleted is False

    def test_relative_key_joins_with_prefix(self):
        """Keys without prefix should be joined with prefix in _resolve_delete_path."""
        from app.services.storage_backend import LocalFileStorage
        storage = LocalFileStorage(prefix="var/exports")
        result = storage._resolve_delete_path("42/test.pdf")
        assert result is not None
        assert result == "var/exports/42/test.pdf"

    def test_prefixed_key_used_as_is(self):
        """Keys that already contain the prefix should be used as-is."""
        from app.services.storage_backend import LocalFileStorage
        storage = LocalFileStorage(prefix="var/exports")
        result = storage._resolve_delete_path("var/exports/42/test.pdf")
        assert result is not None
        assert result == "var/exports/42/test.pdf"


class TestCOSStorageKeyNormalization:
    def test_normalize_key_adds_prefix(self):

        from app.services.storage_backend import COSStorage
        storage = COSStorage.__new__(COSStorage)
        storage._cos_prefix = "var/exports/"
        storage._bucket = "test-bucket"
        storage._region = "ap-guangzhou"

        key = storage._normalize_key("42/test.pdf")
        assert key == "var/exports/42/test.pdf"

    def test_normalize_key_keeps_full_url(self):
        from app.services.storage_backend import COSStorage
        storage = COSStorage.__new__(COSStorage)
        storage._cos_prefix = "var/exports/"
        storage._bucket = "test-bucket"
        storage._region = "ap-guangzhou"

        url = "https://test-bucket.cos.ap-guangzhou.myqcloud.com/var/exports/42/test.pdf"
        key = storage._normalize_key(url)
        assert key == "var/exports/42/test.pdf"

    def test_normalize_key_already_prefixed(self):
        from app.services.storage_backend import COSStorage
        storage = COSStorage.__new__(COSStorage)
        storage._cos_prefix = "var/exports/"
        storage._bucket = "test-bucket"
        storage._region = "ap-guangzhou"

        key = storage._normalize_key("var/exports/42/test.pdf")
        assert key == "var/exports/42/test.pdf"


# ═══════════════════════════════════════════════════
# Snapshot lifecycle tests (re-export, isolation)
# ═══════════════════════════════════════════════════


class TestSnapshotLifecycle:
    @pytest.mark.asyncio
    async def test_create_and_load_snapshot(self, mock_db):
        from app.services.export.snapshot_service import create_snapshot
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        sid = await create_snapshot(mock_db, 1, {"questions": [], "config": {}, "total_count": 0})
        assert sid is not None
        assert len(sid) == 36  # UUID length

    @pytest.mark.asyncio
    async def test_load_nonexistent_snapshot(self, mock_db):
        from app.services.export.snapshot_service import load_snapshot
        mock_db._result.scalar_one_or_none.return_value = None
        result = await load_snapshot(mock_db, "nonexistent-id", 1)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_snapshot(self, mock_db):
        from app.services.export.snapshot_service import delete_snapshot
        mock_snap = MagicMock()
        mock_db._result.scalar_one_or_none.return_value = mock_snap
        mock_db.delete = AsyncMock()
        result = await delete_snapshot(mock_db, "some-id")
        assert result is True


# ═══════════════════════════════════════════════════
# Export storage root path consistency
# ═══════════════════════════════════════════════════


class TestExportStorageRoot:
    def test_get_export_storage_root_creates_dir(self, tmp_path, monkeypatch):
        from app.core.config import settings
        from app.services.storage_backend import get_export_storage_root

        test_dir = str(tmp_path / "var" / "exports")
        monkeypatch.setattr(settings, "EXPORT_DIR", test_dir)
        root = get_export_storage_root()
        assert root == str(tmp_path / "var" / "exports")
        assert (tmp_path / "var" / "exports").exists()


# ═══════════════════════════════════════════════════
# Export API security — unauthorized access
# ═══════════════════════════════════════════════════


class TestExportSecurity:
    def test_resolve_local_path_traversal_blocked(self):
        from app.api.v1.exports import _resolve_local_path
        result = _resolve_local_path("../../etc/passwd")
        assert result is None

    def test_resolve_local_path_normal(self):
        from app.api.v1.exports import _resolve_local_path
        # A normal key should resolve to a valid path under export root
        result = _resolve_local_path("42/test.pdf")
        assert result is not None
        assert "test.pdf" in result
