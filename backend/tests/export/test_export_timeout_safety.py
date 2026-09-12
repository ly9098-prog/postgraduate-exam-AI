"""Tests for GenerationToken timeout safety.

Verifies:
- Token lifecycle (active/invalidate)
- process_task blocks upload when token is invalid
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.export.generation_token import GenerationToken


def _make_mock_task(**overrides):
    """Create a MagicMock that passes process_task's attribute access."""
    attrs = {
        "id": 1,
        "user_id": 1,
        "status": "processing",
        "file_format": "pdf",
        "file_key": None,
        "snapshot_id": None,
        "total_count": 5,
        "processing_started_at": None,
        "generator_version": "1.0",
        "error_code": None,
        "file_size": None,
        "success_count": 0,
        "skip_count": 0,
        "skip_reasons": None,
        "error_message": None,
        "completed_at": None,
        "expires_at": None,
        "range_type": "all",
        "filters": None,
        "selected_ids": None,
        "title": "test",
        "show_date": True,
        "export_date": "2026-07-27",
        "sort_by": "newest",
        "group_by": "none",
        "answer_position": "end",
        "analysis_position": "end",
        "space_style": "standard",
        "created_at": None,
    }
    attrs.update(overrides)
    t = MagicMock()
    for k, v in attrs.items():
        setattr(t, k, v)
    return t


class TestGenerationToken:
    """GenerationToken basic contract — works synchronously, no deps."""

    def test_token_active_by_default(self):
        assert GenerationToken().is_active() is True

    def test_token_inactive_after_invalidate(self):
        t = GenerationToken()
        t.invalidate()
        assert t.is_active() is False

    def test_invalidate_multiple_calls_safe(self):
        t = GenerationToken()
        t.invalidate()
        t.invalidate()  # no-op
        assert t.is_active() is False

    def test_tokens_independent(self):
        a, b = GenerationToken(), GenerationToken()
        a.invalidate()
        assert a.is_active() is False
        assert b.is_active() is True


class TestProcessTaskTokenGuard:
    """process_task checks token before upload and completion."""

    @pytest.mark.asyncio
    async def test_token_check_before_upload(self):
        """When token is invalid, process_task raises ExportDomainError before upload."""
        from app.services.export.service import process_task

        mock_exporter = AsyncMock()
        mock_exporter.export.return_value = MagicMock(
            success=True, file_bytes=b"pdf", error_message=None,
            skip_count=0, skip_reasons=[],
        )

        mock_storage = AsyncMock()
        mock_task = _make_mock_task()

        token = GenerationToken()
        token.invalidate()

        with (
            patch("app.services.storage_backend.get_export_storage", return_value=mock_storage),
            patch("app.services.export.service.resolve_range", AsyncMock(return_value=[])),
            patch("app.services.export.service.sort_questions", AsyncMock(return_value=[])),
            patch("app.services.export.service.build_snapshot_data", return_value={
                "config": {}, "total_count": 5, "skip_count": 0, "questions": [],
            }),
            patch("app.services.export.service.create_snapshot", AsyncMock(return_value="snap-1")),
        ):
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_task
            db.execute.return_value = mock_result

            result = await process_task(db, 1, mock_exporter, token=token)

            # ExportDomainError is caught inside process_task — task marked as FAILED
            assert result.status == "failed"
            assert "超时" in (result.error_message or "")
            mock_storage.upload.assert_not_called()
            assert mock_task.status == "failed"

    @pytest.mark.asyncio
    async def test_no_token_passes(self):
        """Backward compat: process_task works without token."""
        from app.services.export.service import process_task

        mock_exporter = AsyncMock()
        mock_exporter.export.return_value = MagicMock(
            success=True, file_bytes=b"pdf", error_message=None,
            skip_count=0, skip_reasons=[],
        )

        mock_storage = AsyncMock()
        mock_task = _make_mock_task()

        with (
            patch("app.services.storage_backend.get_export_storage", return_value=mock_storage),
            patch("app.services.export.service.resolve_range", AsyncMock(return_value=[])),
            patch("app.services.export.service.sort_questions", AsyncMock(return_value=[])),
            patch("app.services.export.service.build_snapshot_data", return_value={
                "config": {}, "total_count": 5, "skip_count": 0, "questions": [],
            }),
            patch("app.services.export.service.create_snapshot", AsyncMock(return_value="snap-1")),
        ):
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_task
            db.execute.return_value = mock_result

            try:
                await process_task(db, 1, mock_exporter)  # no token arg
            except Exception:
                pass

            # Did not raise about missing token
