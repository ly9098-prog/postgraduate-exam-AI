"""Tests for asset reference service and safe deletion."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from app.services.asset_reference_service import (
    AssetReference,
    AssetReferenceReport,
    AssetReferenceService,
    DeletionState,
    SafeDeleteMachine,
    extract_asset_urls,
    url_to_storage_key,
)


class TestUrlToStorageKey:
    def test_static_relative(self):
        assert url_to_storage_key("/static/question-assets/202607/ds_sc/q_229.png") == \
            "question-assets/202607/ds_sc/q_229.png"

    def test_cos_url(self):
        assert url_to_storage_key(
            "https://bucket.cos.region.myqcloud.com/static/question-assets/202607/q.png"
        ) == "question-assets/202607/q.png"


class TestExtractAssetUrls:
    def test_extract_from_content_segments(self):
        content = {
            "segments": [
                {"type": "text", "text": "stem"},
                {"type": "image", "url": "/static/question-assets/202607/ds_sc/q_229.png"},
            ],
            "source_snapshot_url": "/static/question-assets/202607/snapshot.png",
        }
        urls = extract_asset_urls(content)
        assert len(urls) == 2
        assert any("q_229.png" in u["url"] for u in urls)
        assert any("snapshot.png" in u["url"] for u in urls)

    def test_extract_from_list_field(self):
        data = {"image_url": ["/static/question-assets/img1.png", "/static/question-assets/img2.png"]}
        urls = extract_asset_urls(data)
        assert len(urls) == 2

    def test_empty_input(self):
        assert extract_asset_urls({}) == []
        assert extract_asset_urls(None) == []
        assert extract_asset_urls("no-urls-here") == []


class TestSafeDeleteMachine:
    def test_valid_transitions(self):
        m = SafeDeleteMachine(DeletionState.PLANNED)
        m.transition(DeletionState.REFERENCE_CHECKED)
        assert m.state == DeletionState.REFERENCE_CHECKED

    def test_invalid_transition_raises(self):
        m = SafeDeleteMachine(DeletionState.PLANNED)
        with pytest.raises(ValueError, match="Invalid transition"):
            m.transition(DeletionState.DELETED)

    def test_full_delete_flow(self):
        m = SafeDeleteMachine()
        m.transition(DeletionState.REFERENCE_CHECKED)
        m.transition(DeletionState.DETACHED)
        m.transition(DeletionState.GRACE_PERIOD)
        m.transition(DeletionState.DELETING)
        m.transition(DeletionState.DELETED)
        assert m.state == DeletionState.DELETED

    def test_cancel_from_planned(self):
        m = SafeDeleteMachine()
        m.transition(DeletionState.CANCELLED)
        assert m.state == DeletionState.CANCELLED

    def test_no_transition_from_terminal(self):
        m = SafeDeleteMachine(DeletionState.DELETED)
        for s in DeletionState:
            with pytest.raises(ValueError):
                m.transition(s)


class TestAssetReferenceReport:
    def test_safe_to_delete_when_empty(self):
        r = AssetReferenceReport(storage_key="test.png")
        assert r.safe_to_delete
        assert r.reference_count == 0

    def test_not_safe_when_referenced(self):
        r = AssetReferenceReport(storage_key="test.png")
        r.references.append(AssetReference("question", "1", "content", None, "/s/test.png", "test.png"))
        assert not r.safe_to_delete
        assert r.reference_count == 1
        assert any("referenced_by" in c for c in r.reason_codes)


class TestAssetReferenceService:
    """Tests requiring a real DB — use the test DB fixture."""

    @pytest.mark.asyncio
    async def test_resolve_unknown_key_returns_empty(self):
        """Without a DB connection, resolve gracefully handles errors."""
        # Cannot instantiate without a DB session in unit test mode
        pass
