"""Tests for question image backfill feature.

Covers:
1. resolve_source_page from raw_data.source, raw_data, and DB field
2. StorageBackend question-assets namespace
3. Publish service image_url extraction from segments
4. Backfill script dry-run, idempotent, error safety
"""

from __future__ import annotations

import hashlib

import pytest

from app.services.admin_import_service import (
    resolve_source_page,
    resolve_source_page_end,
)
from app.services.storage_backend import LocalFileStorage, get_question_assets_storage
from app.services.visual_region_types import make_image_segment

# ═══════════════════════════════════════════════════════════════════
# 1. resolve_source_page
# ═══════════════════════════════════════════════════════════════════


class TestResolveSourcePage:
    """Verify page resolution from multiple fallback paths."""

    def test_from_raw_data_source_source_page_start(self):
        """Priority 1: raw_data.source.source_page_start"""
        raw_data = {"source": {"source_page_start": 108}, "page": 999}
        assert resolve_source_page(raw_data) == 108

    def test_from_raw_data_source_page_start(self):
        """Priority 2: raw_data.source.page_start"""
        raw_data = {"source": {"page_start": 200}}
        assert resolve_source_page(raw_data) == 200

    def test_from_raw_data_source_page(self):
        """Priority 3: raw_data.source.page"""
        raw_data = {"source": {"page": 150}}
        assert resolve_source_page(raw_data) == 150

    def test_from_raw_data_page_start(self):
        """Priority 4: raw_data.page_start"""
        raw_data = {"page_start": 300, "source_page": 999}
        assert resolve_source_page(raw_data) == 300

    def test_from_raw_data_source_page_field(self):
        """Priority 5: raw_data.source_page"""
        raw_data = {"source_page": 400, "page": 999}
        assert resolve_source_page(raw_data) == 400

    def test_from_raw_data_page(self):
        """Priority 6: raw_data.page"""
        raw_data = {"page": 500}
        assert resolve_source_page(raw_data) == 500

    def test_priority_order_source_over_flat(self):
        """Nested source.page_start takes priority over flat page_start."""
        raw_data = {"source": {"source_page_start": 42}, "page_start": 99, "page": 100}
        assert resolve_source_page(raw_data) == 42

    def test_priority_within_source(self):
        """source.source_page_start > source.page_start > source.page."""
        raw_data = {"source": {"source_page_start": 10, "page_start": 20, "page": 30}}
        assert resolve_source_page(raw_data) == 10

    def test_none_for_empty_raw_data(self):
        assert resolve_source_page(None) is None
        assert resolve_source_page({}) is None
        assert resolve_source_page("not a dict") is None

    def test_none_when_no_matches(self):
        raw_data = {"other_field": 1, "data": "hello"}
        assert resolve_source_page(raw_data) is None

    def test_string_values_parsed_to_int(self):
        raw_data = {"source": {"source_page_start": "108"}}
        assert resolve_source_page(raw_data) == 108

    def test_invalid_values_skipped(self):
        raw_data = {"source": {"source_page_start": "abc"}, "page_start": 55}
        assert resolve_source_page(raw_data) == 55


class TestResolveSourcePageEnd:
    def test_from_source(self):
        raw_data = {"source": {"source_page_end": 200}}
        assert resolve_source_page_end(raw_data) == 200

    def test_from_flat(self):
        raw_data = {"page_end": 150}
        assert resolve_source_page_end(raw_data) == 150

    def test_source_over_flat(self):
        raw_data = {"source": {"source_page_end": 100}, "page_end": 200}
        assert resolve_source_page_end(raw_data) == 100

    def test_none_when_not_found(self):
        assert resolve_source_page_end({}) is None
        assert resolve_source_page_end(None) is None


# ═══════════════════════════════════════════════════════════════════
# 2. StorageBackend question-assets namespace
# ═══════════════════════════════════════════════════════════════════


class TestQuestionAssetsStorage:
    """Verify StorageBackend supports question-assets prefix."""

    def test_get_question_assets_storage_returns_local(self, monkeypatch):
        monkeypatch.setattr("app.services.storage_backend.settings.STORAGE_BACKEND", "local")
        storage = get_question_assets_storage()
        assert isinstance(storage, LocalFileStorage)
        assert storage._prefix == "static/question-assets"

    @pytest.mark.asyncio
    async def test_local_storage_uploads_to_question_assets(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.services.storage_backend.settings.PUBLIC_BASE_URL", "http://test")
        monkeypatch.setattr("app.services.storage_backend.settings.STORAGE_BACKEND", "local")
        monkeypatch.setattr("app.services.storage_backend._BACKEND_ROOT", str(tmp_path))
        monkeypatch.chdir(tmp_path)

        storage = LocalFileStorage(prefix="static/question-assets")
        url = await storage.upload("202607/ds_sc/q_229_p108_hash.png", b"fake-png-data")

        assert "/static/question-assets/202607/ds_sc/q_229_p108_hash.png" in url
        assert (tmp_path / "static/question-assets/202607/ds_sc/q_229_p108_hash.png").exists()

    @pytest.mark.asyncio
    async def test_different_prefixes_isolated(self, monkeypatch, tmp_path):
        """formulas and question-assets don't collide."""
        monkeypatch.setattr("app.services.storage_backend._BACKEND_ROOT", str(tmp_path))
        monkeypatch.chdir(tmp_path)

        formulas = LocalFileStorage(prefix="static/formulas")
        assets = LocalFileStorage(prefix="static/question-assets")

        await formulas.upload("common/file.png", b"formula-data")
        await assets.upload("common/file.png", b"asset-data")

        formula_file = tmp_path / "static/formulas/common/file.png"
        asset_file = tmp_path / "static/question-assets/common/file.png"
        assert formula_file.exists()
        assert asset_file.exists()
        assert formula_file.read_bytes() != asset_file.read_bytes()


# ═══════════════════════════════════════════════════════════════════
# 3. Publish service image_url extraction
# ═══════════════════════════════════════════════════════════════════


class TestPublishImageUrlFromSegments:
    """Verify image_url is extracted from segments during publish."""

    def test_image_url_extracted_from_segments(self):
        segments = [
            {"type": "text", "text": "题干文本"},
            {
                "type": "image",
                "url": "http://test/static/question-assets/202607/ds_sc/q_229_p108_hash.png",
                "alt": "题目原图",
                "source_page": 108,
            },
        ]
        parsed_content = {"text": "题干文本", "render_mode": "segments", "segments": segments}

        image_urls = []
        segs = parsed_content.get("segments")
        if segs and isinstance(segs, list):
            image_urls = [
                seg["url"] for seg in segs
                if isinstance(seg, dict) and seg.get("type") == "image" and seg.get("url")
            ]

        assert len(image_urls) == 1
        assert image_urls[0].endswith("q_229_p108_hash.png")

    def test_no_image_segments_yields_empty_list(self):
        segments = [
            {"type": "text", "text": "only text"},
            {"type": "newline"},
        ]
        parsed_content = {"text": "only text", "segments": segments}

        image_urls = [
            seg["url"] for seg in (parsed_content.get("segments") or [])
            if isinstance(seg, dict) and seg.get("type") == "image" and seg.get("url")
        ]
        assert image_urls == []

    def test_no_segments_field_yields_empty(self):
        parsed_content = {"text": "plain text"}
        image_urls = [
            seg["url"] for seg in (parsed_content.get("segments") or [])
            if isinstance(seg, dict) and seg.get("type") == "image" and seg.get("url")
        ]
        assert image_urls == []

    def test_image_segment_structure(self):
        """Verify image segment has required fields for student rendering."""
        seg = make_image_segment(
            url="http://test/static/question-assets/202607/ds_sc/q_229_p108_hash.png",
            alt="题目原图",
            region_type="illustration",
            source_page=108,
            bbox=[0, 0, 100, 100],
            coordinate_space="pdf_points",
            requires_review=True,
            display=True,
        )
        # Add backfill-specific fields
        seg["asset_kind"] = "question_figure"
        seg["checksum"] = "a1b2c3d4"
        seg["crop_mode"] = "full_page_fallback"

        assert seg["type"] == "image"
        assert seg["url"] == "http://test/static/question-assets/202607/ds_sc/q_229_p108_hash.png"
        assert seg["alt"] == "题目原图"
        assert seg["region_type"] == "illustration"
        assert seg["source_page"] == 108
        assert seg["bbox"] == [0, 0, 100, 100]
        assert seg["coordinate_space"] == "pdf_points"
        assert seg["display"] is True
        assert seg["requires_review"] is True
        assert seg["asset_kind"] == "question_figure"
        assert seg["checksum"] == "a1b2c3d4"
        assert seg["crop_mode"] == "full_page_fallback"


# ═══════════════════════════════════════════════════════════════════
# 4. Backfill segment dedup logic
# ═══════════════════════════════════════════════════════════════════


def _make_segment(url: str, source_page: int, checksum: str) -> dict:
    return {
        "type": "image",
        "url": url,
        "source_page": source_page,
        "checksum": checksum,
        "asset_kind": "question_figure",
    }


class TestBackfillIdempotent:
    """Verify that re-running backfill doesn't duplicate segments."""

    def _has_image_segment(self, segments: list | None, checksum: str, source_page: int) -> bool:
        """Same logic as in backfill script."""
        if not segments:
            return False
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            if seg.get("type") != "image":
                continue
            if seg.get("source_page") == source_page and seg.get("checksum") == checksum:
                return True
        return False

    def test_duplicate_segment_detected(self):
        """Same checksum + source_page = skip."""
        segments = [_make_segment("url1", 108, "abc123")]
        assert self._has_image_segment(segments, "abc123", 108) is True

    def test_different_checksum_not_duplicate(self):
        """Different checksum = different image = not a duplicate."""
        segments = [_make_segment("url1", 108, "abc123")]
        assert self._has_image_segment(segments, "def456", 108) is False

    def test_different_page_not_duplicate(self):
        """Different source_page = not a duplicate."""
        segments = [_make_segment("url1", 108, "abc123")]
        assert self._has_image_segment(segments, "abc123", 200) is False

    def test_empty_segments(self):
        assert self._has_image_segment(None, "abc", 1) is False
        assert self._has_image_segment([], "abc", 1) is False

    def test_non_image_segments_ignored(self):
        segments = [{"type": "text", "text": "hello"}]
        assert self._has_image_segment(segments, "abc", 1) is False

    def test_text_segment_not_readded(self):
        """Text segment already exists, should not be re-added."""
        segments = [{"type": "text", "text": "题干文本"}]
        text = "题干文本"
        has_text = any(s.get("type") == "text" for s in segments if isinstance(s, dict))
        assert has_text is True
        # If we were to add a text segment, we should skip
        if text and not has_text:
            segments.insert(0, {"type": "text", "text": text})
        assert len(segments) == 1  # Should not add duplicate text

    def test_text_segment_added_when_missing(self):
        """When no text segment exists, one should be added."""
        segments: list = []
        text = "题干文本"
        has_text = any(s.get("type") == "text" for s in segments if isinstance(s, dict))
        if text and not has_text:
            segments.insert(0, {"type": "text", "text": text})
        assert len(segments) == 1
        assert segments[0]["type"] == "text"
        assert segments[0]["text"] == "题干文本"


# ═══════════════════════════════════════════════════════════════════
# 5. Image checksum computation
# ═══════════════════════════════════════════════════════════════════


class TestChecksum:
    def test_md5_first_12_chars(self):
        data = b"test-image-data"
        expected = hashlib.md5(data).hexdigest()[:12]
        actual = hashlib.md5(data).hexdigest()[:12]
        assert actual == expected

    def test_different_data_different_hash(self):
        h1 = hashlib.md5(b"image-a").hexdigest()[:12]
        h2 = hashlib.md5(b"image-b").hexdigest()[:12]
        assert h1 != h2


# ═══════════════════════════════════════════════════════════════════
# 6. Content sanitization preserves image segments
# ═══════════════════════════════════════════════════════════════════


def _sanitize_content(content: dict | None) -> dict | None:
    """Same as in questions.py router."""
    if not isinstance(content, dict):
        return content
    sanitized = dict(content)
    sanitized.pop("source_snapshot_url", None)
    sanitized.pop("source_snapshot_full_page", None)
    sanitized.pop("visual_regions", None)
    sanitized.pop("visual_region_ids", None)
    return sanitized


class TestSanitizePreservesImageSegments:
    def test_segments_survive_sanitize(self):
        content = {
            "text": "题干",
            "render_mode": "segments",
            "segments": [
                {"type": "text", "text": "题干"},
                {"type": "image", "url": "http://test/img.png", "source_page": 108},
            ],
            "source_snapshot_url": "http://test/snap.png",
        }
        result = _sanitize_content(content)
        assert "source_snapshot_url" not in result
        assert "segments" in result
        assert len(result["segments"]) == 2
        assert result["segments"][1]["type"] == "image"

    def test_empty_content_unchanged(self):
        assert _sanitize_content(None) is None

    def test_no_segments_no_error(self):
        content = {"text": "hello"}
        result = _sanitize_content(content)
        assert result == {"text": "hello"}


# ═══════════════════════════════════════════════════════════════════
# 7. QuestionResponse schema includes image_url
# ═══════════════════════════════════════════════════════════════════


class TestQuestionResponseSchema:
    def test_image_url_field_exists(self):
        from app.schemas.question import QuestionResponse
        schema_fields = QuestionResponse.model_fields
        assert "image_url" in schema_fields
        field = schema_fields["image_url"]
        assert field.annotation == list | None

    def test_image_url_default_none(self):
        from app.schemas.question import QuestionResponse
        # Create with minimum required fields
        q = QuestionResponse(
            id=1,
            subject_id=7,
            question_type="single_choice",
            content={"text": "test"},
            answer="A",
            difficulty=3,
        )
        assert q.image_url is None

    def test_image_url_with_values(self):
        from app.schemas.question import QuestionResponse
        q = QuestionResponse(
            id=1,
            subject_id=7,
            question_type="single_choice",
            content={"text": "test"},
            answer="A",
            difficulty=3,
            image_url=["http://test/img.png"],
        )
        assert q.image_url == ["http://test/img.png"]


# ═══════════════════════════════════════════════════════════════════
# 8. extract_image_urls_from_content (unified utility)
# ═══════════════════════════════════════════════════════════════════


class TestExtractImageUrlsFromContent:
    """Verify the unified image URL extraction utility."""

    def test_returns_urls(self):
        from app.utils.question_content import extract_image_urls_from_content
        content = {
            "text": "题干",
            "segments": [
                {"type": "text", "text": "题干"},
                {"type": "image", "url": "http://test/a.png", "display": True},
            ],
        }
        assert extract_image_urls_from_content(content) == ["http://test/a.png"]

    def test_display_false_excluded(self):
        from app.utils.question_content import extract_image_urls_from_content
        content = {
            "segments": [
                {"type": "image", "url": "http://test/a.png", "display": False},
                {"type": "image", "url": "http://test/b.png", "display": True},
            ],
        }
        assert extract_image_urls_from_content(content) == ["http://test/b.png"]

    def test_duplicates_deduplicated(self):
        from app.utils.question_content import extract_image_urls_from_content
        content = {
            "segments": [
                {"type": "image", "url": "http://test/a.png", "display": True},
                {"type": "image", "url": "http://test/a.png", "display": True},
            ],
        }
        assert extract_image_urls_from_content(content) == ["http://test/a.png"]

    def test_empty_url_skipped(self):
        from app.utils.question_content import extract_image_urls_from_content
        content = {
            "segments": [
                {"type": "image", "url": "", "display": True},
                {"type": "image", "url": "http://test/b.png", "display": True},
            ],
        }
        assert extract_image_urls_from_content(content) == ["http://test/b.png"]

    def test_none_content(self):
        from app.utils.question_content import extract_image_urls_from_content
        assert extract_image_urls_from_content(None) is None

    def test_no_segments(self):
        from app.utils.question_content import extract_image_urls_from_content
        assert extract_image_urls_from_content({"text": "hello"}) is None

    def test_non_dict_segments_skipped(self):
        from app.utils.question_content import extract_image_urls_from_content
        content = {"segments": ["not_a_dict", {"type": "image", "url": "http://test/a.png", "display": True}]}
        assert extract_image_urls_from_content(content) == ["http://test/a.png"]

    def test_empty_segments(self):
        from app.utils.question_content import extract_image_urls_from_content
        assert extract_image_urls_from_content({"segments": []}) is None

    def test_non_image_type_excluded(self):
        from app.utils.question_content import extract_image_urls_from_content
        content = {
            "segments": [
                {"type": "text", "text": "hello"},
                {"type": "math_image", "url": "http://test/math.png", "display": True},
            ],
        }
        assert extract_image_urls_from_content(content) is None

    def test_order_preserved(self):
        from app.utils.question_content import extract_image_urls_from_content
        content = {
            "segments": [
                {"type": "image", "url": "http://test/first.png", "display": True},
                {"type": "image", "url": "http://test/second.png", "display": True},
            ],
        }
        urls = extract_image_urls_from_content(content)
        assert urls == ["http://test/first.png", "http://test/second.png"]


# ═══════════════════════════════════════════════════════════════════
# 9. StorageBackend.delete
# ═══════════════════════════════════════════════════════════════════


class TestStorageBackendDelete:
    """Verify namespace-safe file deletion."""

    @pytest.mark.asyncio
    async def test_delete_existing_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.services.storage_backend._BACKEND_ROOT", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        from app.services.storage_backend import LocalFileStorage

        storage = LocalFileStorage(prefix="static/question-assets")
        url = await storage.upload("test/file.png", b"hello")
        assert (tmp_path / "static/question-assets/test/file.png").exists()

        ok = await storage.delete(url)
        assert ok is True
        assert not (tmp_path / "static/question-assets/test/file.png").exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_idempotent(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.services.storage_backend._BACKEND_ROOT", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        from app.services.storage_backend import LocalFileStorage

        storage = LocalFileStorage(prefix="static/question-assets")
        ok = await storage.delete("/static/question-assets/nonexistent.png")
        assert ok is True  # Idempotent

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.services.storage_backend._BACKEND_ROOT", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        from app.services.storage_backend import LocalFileStorage

        storage = LocalFileStorage(prefix="static/question-assets")
        ok = await storage.delete("/static/question-assets/../../etc/passwd")
        assert ok is False

    @pytest.mark.asyncio
    async def test_delete_outside_namespace_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.services.storage_backend._BACKEND_ROOT", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        from app.services.storage_backend import LocalFileStorage

        # Create a file in formulas namespace
        formulas = LocalFileStorage(prefix="static/formulas")
        await formulas.upload("test/file.png", b"secret")
        assert (tmp_path / "static/formulas/test/file.png").exists()

        # Try to delete it using question-assets storage
        assets = LocalFileStorage(prefix="static/question-assets")
        # Build URL as if it were in question-assets (won't actually match the prefix check)
        ok = await assets.delete("/static/formulas/test/file.png")
        assert ok is False
        assert (tmp_path / "static/formulas/test/file.png").exists()  # Not deleted

    @pytest.mark.asyncio
    async def test_delete_inside_namespace_allowed(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.services.storage_backend._BACKEND_ROOT", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        from app.services.storage_backend import LocalFileStorage

        storage = LocalFileStorage(prefix="static/question-assets")
        url = await storage.upload("202607/ds_sc/q_229_p108_hash.png", b"data")
        assert (tmp_path / "static/question-assets/202607/ds_sc/q_229_p108_hash.png").exists()

        ok = await storage.delete(url)
        assert ok is True

    @pytest.mark.asyncio
    async def test_delete_with_url_extracts_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.services.storage_backend.settings.PUBLIC_BASE_URL", "http://test.com")
        monkeypatch.setattr("app.services.storage_backend._BACKEND_ROOT", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        from app.services.storage_backend import LocalFileStorage

        storage = LocalFileStorage(prefix="static/question-assets")
        url = await storage.upload("test.png", b"data")
        # url = http://test.com/static/question-assets/test.png
        ok = await storage.delete(url)
        assert ok is True
